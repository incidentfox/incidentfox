import os
from abc import ABC, abstractmethod

import torch
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_random_exponential
from transformers import T5ForConditionalGeneration, T5Tokenizer

from .usage_log import _Timer, log_usage


class BaseQAModel(ABC):
    @abstractmethod
    def answer_question(self, context, question):
        pass


class GPT3QAModel(BaseQAModel):
    def __init__(self, model="text-davinci-003"):
        """
        Initializes the GPT-3 model with the specified model version.

        Args:
            model (str, optional): The GPT-3 model version to use for generating summaries. Defaults to "text-davinci-003".
        """
        self.model = model
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
    def answer_question(self, context, question, max_tokens=150, stop_sequence=None):
        """
        Generates a summary of the given context using the GPT-3 model.

        Args:
            context (str): The text to summarize.
            max_tokens (int, optional): The maximum number of tokens in the generated summary. Defaults to 150.
            stop_sequence (str, optional): The sequence at which to stop summarization. Defaults to None.

        Returns:
            str: The generated summary.
        """
        try:
            response = self.client.completions.create(
                prompt=f"using the folloing information {context}. Answer the following question in less than 5-7 words, if possible: {question}",
                temperature=0,
                max_tokens=max_tokens,
                top_p=1,
                frequency_penalty=0,
                presence_penalty=0,
                stop=stop_sequence,
                model=self.model,
            )
            return response.choices[0].text.strip()

        except Exception as e:
            print(e)
            return ""


class GPT3TurboQAModel(BaseQAModel):
    def __init__(self, model="gpt-3.5-turbo"):
        """
        Initializes the GPT-3 model with the specified model version.

        Args:
            model (str, optional): The GPT-3 model version to use for generating summaries. Defaults to "text-davinci-003".
        """
        self.model = model
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
    def _attempt_answer_question(
        self, context, question, max_tokens=150, stop_sequence=None
    ):
        """
        Generates a summary of the given context using the GPT-3 model.

        Args:
            context (str): The text to summarize.
            max_tokens (int, optional): The maximum number of tokens in the generated summary. Defaults to 150.
            stop_sequence (str, optional): The sequence at which to stop summarization. Defaults to None.

        Returns:
            str: The generated summary.
        """
        # Keep the prompt simple and explicit: always produce a text answer.
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant. Answer the user's question using ONLY the provided context. "
                    'If the context is insufficient, say "I don\'t know based on the provided context." '
                    "Always respond with plain text (no empty responses)."
                ),
            },
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion:\n{question}\n\nAnswer:",
            },
        ]
        # Prefer max_completion_tokens (newer chat models), fall back to legacy max_tokens if needed.
        timer = _Timer()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0,
                max_completion_tokens=max_tokens,
            )
        except Exception as e:
            msg = str(e)
            if "Unsupported parameter" in msg and "max_tokens" in msg:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0,
                    max_tokens=max_tokens,
                )
            else:
                raise

        log_usage(
            kind="qa",
            model=self.model,
            usage=getattr(response, "usage", None),
            duration_s=timer.elapsed(),
            meta={"max_completion_tokens": int(max_tokens)},
        )
        content = getattr(response.choices[0].message, "content", None)
        if isinstance(content, str):
            content = content.strip()
        else:
            content = ""

        # Some models/tools can (rarely) produce an empty message; ensure a stable fallback.
        if not content:
            content = "I don't know based on the provided context."
        return content

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
    def answer_question(self, context, question, max_tokens=150, stop_sequence=None):

        try:
            ans = self._attempt_answer_question(
                context, question, max_tokens=max_tokens, stop_sequence=stop_sequence
            )
            if not isinstance(ans, str):
                raise TypeError(f"QA model returned non-string: {type(ans)}")
            ans = ans.strip()
            if not ans:
                return "I don't know based on the provided context."
            return ans
        except Exception as e:
            # Never return the exception object (it can break downstream tokenization).
            raise RuntimeError(f"QA failed ({self.model}): {e}") from e


class GPT4QAModel(BaseQAModel):
    def __init__(self, model="gpt-4"):
        """
        Initializes the GPT-3 model with the specified model version.

        Args:
            model (str, optional): The GPT-3 model version to use for generating summaries. Defaults to "text-davinci-003".
        """
        self.model = model
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
    def _attempt_answer_question(
        self, context, question, max_tokens=150, stop_sequence=None
    ):
        """
        Generates a summary of the given context using the GPT-3 model.

        Args:
            context (str): The text to summarize.
            max_tokens (int, optional): The maximum number of tokens in the generated summary. Defaults to 150.
            stop_sequence (str, optional): The sequence at which to stop summarization. Defaults to None.

        Returns:
            str: The generated summary.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are Question Answering Portal"},
                {
                    "role": "user",
                    "content": f"Given Context: {context} Give the best full answer amongst the option to question {question}",
                },
            ],
            temperature=0,
        )

        return response.choices[0].message.content.strip()

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
    def answer_question(self, context, question, max_tokens=150, stop_sequence=None):

        try:
            return self._attempt_answer_question(
                context, question, max_tokens=max_tokens, stop_sequence=stop_sequence
            )
        except Exception as e:
            print(e)
            return e


class UnifiedQAModel(BaseQAModel):
    def __init__(self, model_name="allenai/unifiedqa-v2-t5-3b-1363200"):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = T5ForConditionalGeneration.from_pretrained(model_name).to(
            self.device
        )
        self.tokenizer = T5Tokenizer.from_pretrained(model_name)

    def run_model(self, input_string, **generator_args):
        input_ids = self.tokenizer.encode(input_string, return_tensors="pt").to(
            self.device
        )
        res = self.model.generate(input_ids, **generator_args)
        return self.tokenizer.batch_decode(res, skip_special_tokens=True)

    def answer_question(self, context, question):
        input_string = question + " \\n " + context
        output = self.run_model(input_string)
        return output[0]
