import json
import logging
import os
import re
import threading
from abc import ABC, abstractmethod
from datetime import datetime

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_random_exponential

from .usage_log import _Timer, log_usage

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)


class BaseSummarizationModel(ABC):
    @abstractmethod
    def summarize(self, context, max_tokens=150):
        pass


class LayerAwareSummarizationMixin:
    """
    Optional mixin interface. If present, TreeBuilder will call summarize_layer()
    so you can vary prompt/length by target layer.
    """

    def summarize_layer(
        self, context: str, *, layer: int, max_tokens: int
    ) -> str:  # pragma: no cover
        raise NotImplementedError


class GPT3TurboSummarizationModel(BaseSummarizationModel):
    def __init__(self, model="gpt-3.5-turbo"):

        self.model = model

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
    def summarize(self, context, max_tokens=500, stop_sequence=None):

        client = OpenAI()
        timer = _Timer()
        # We hard-cap generation with max_completion_tokens, but we ALSO ask the model to aim shorter
        # so we don't lose content due to truncation-at-cap.
        max_tokens = int(max_tokens)
        target_words = max(40, int(max_tokens * 0.7))
        messages = [
            {
                "role": "system",
                "content": (
                    "You summarize a bundle of documentation chunks for a hierarchical retrieval tree. "
                    "Be mostly abstractive (paraphrase, don't copy long sentences verbatim). "
                    "Do NOT include code blocks or YAML unless they are key detail; describe them at a high level in general. "
                    "Output plain text only."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Write a summary of the text.\n"
                    f"- Length: <= {target_words} words.\n"
                    "- Focus on main concepts, constraints, and relationships.\n"
                    "- Do not quote large spans.\n\n"
                    f"Text:\n{context}"
                ),
            },
        ]

        # Some newer OpenAI chat models (e.g. gpt-5.x) require `max_completion_tokens`
        # instead of `max_tokens`. We'll try `max_completion_tokens` first and fall back.
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_completion_tokens=max_tokens,
            )
            log_usage(
                kind="summarize",
                model=self.model,
                usage=getattr(response, "usage", None),
                duration_s=timer.elapsed(),
                meta={"max_completion_tokens": int(max_tokens)},
            )
            return response.choices[0].message.content
        except Exception as e:
            msg = str(e)
            if "max_completion_tokens" in msg or "Unsupported parameter" in msg:
                # fall back to legacy param name
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                )
                log_usage(
                    kind="summarize",
                    model=self.model,
                    usage=getattr(response, "usage", None),
                    duration_s=timer.elapsed(),
                    meta={"max_tokens": int(max_tokens)},
                )
                return response.choices[0].message.content
            raise


class OpenAILayeredSummarizationModel(
    BaseSummarizationModel, LayerAwareSummarizationMixin
):
    """
    Layer-aware summarizer that can produce different styles at different layers:
    - details: dense summary
    - summary: concise paragraph
    - bullets: 6-10 terse bullet points (good for top layers / browsing)
    - keywords: comma-separated keywords/keyphrases (very top layer if desired)
    """

    def __init__(
        self,
        model: str = "gpt-5.2",
        *,
        default_mode: str = "details",
        mode_by_layer=None,
    ):
        self.model = model
        self.default_mode = default_mode or "details"
        self.mode_by_layer = dict(mode_by_layer or {})
        # Bump this whenever prompts/format enforcement changes (also useful for cache versioning).
        self.prompt_version = "v3-abstractive-guard"
        # OpenAI client objects are not guaranteed thread-safe; use one per thread.
        self._tls = threading.local()
        self._debug_lock = threading.Lock()

    def _debug_enabled_for(self, event: str) -> bool:
        path = os.environ.get("RAPTOR_SUMMARY_DEBUG_LOG_PATH", "").strip()
        if not path:
            return False
        raw = os.environ.get("RAPTOR_SUMMARY_DEBUG_EVENTS", "guard").strip()
        if not raw:
            return False
        allowed = {x.strip().lower() for x in raw.split(",") if x.strip()}
        return (event or "").strip().lower() in allowed or "all" in allowed

    def _debug_log(
        self, *, event: str, messages: list[dict], output: str, meta: dict
    ) -> None:
        """
        Append a JSONL record with the raw prompt (messages) + raw output for reproducibility.
        Enabled only when RAPTOR_SUMMARY_DEBUG_LOG_PATH is set.
        """
        path = os.environ.get("RAPTOR_SUMMARY_DEBUG_LOG_PATH", "").strip()
        if not path:
            return
        # Optional safety cap to avoid runaway log sizes; set to 0 to disable.
        try:
            cap = int(
                os.environ.get("RAPTOR_SUMMARY_DEBUG_MAX_CHARS", "0").strip() or "0"
            )
        except Exception:
            cap = 0

        rec = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "event": event,
            "meta": meta,
            "messages": messages,
            "output": output,
        }

        if cap and isinstance(rec.get("output"), str) and len(rec["output"]) > cap:
            rec["output"] = rec["output"][:cap] + "\n…[TRUNCATED output]…"
        if cap and isinstance(rec.get("messages"), list):
            # Cap message contents (best-effort) if extremely large.
            for m in rec["messages"]:
                if (
                    isinstance(m, dict)
                    and isinstance(m.get("content"), str)
                    and len(m["content"]) > cap
                ):
                    m["content"] = m["content"][:cap] + "\n…[TRUNCATED content]…"

        line = json.dumps(rec, ensure_ascii=False)
        with self._debug_lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def _client(self) -> OpenAI:
        c = getattr(self._tls, "client", None)
        if c is None:
            c = OpenAI()
            self._tls.client = c
        return c

    _WORD_RE = re.compile(r"[a-z0-9]+", re.I)

    @classmethod
    def _ngram_overlap_ratio(cls, a: str, b: str, *, n: int = 5) -> float:
        """
        Approximate "extractiveness" as ratio of n-grams in `a` that also appear in `b`.
        1.0 means `a` is fully contained in `b` at the n-gram level.
        """
        wa = cls._WORD_RE.findall(a or "")
        wb = cls._WORD_RE.findall(b or "")
        if len(wa) < n or len(wb) < n:
            return 0.0
        ga = {" ".join(wa[i : i + n]).lower() for i in range(0, len(wa) - n + 1)}
        gb = {" ".join(wb[i : i + n]).lower() for i in range(0, len(wb) - n + 1)}
        if not ga:
            return 0.0
        return float(len(ga & gb) / len(ga))

    @staticmethod
    def _target_words(max_tokens: int) -> int:
        # Heuristic: ask for fewer words than the API hard cap to avoid truncation-at-cap.
        # (~1 token ≈ 0.75 words in English prose, but varies; 0.65–0.75 is a decent safety band.)
        mt = max(1, int(max_tokens))
        return max(25, int(mt * 0.7))

    def _messages(
        self, context: str, *, mode: str, layer: int, max_tokens: int
    ) -> list[dict]:
        mode = (mode or "details").strip().lower()
        target_words = self._target_words(int(max_tokens))
        if mode == "bullets":
            sys = (
                "You create a high-level outline for browsing. "
                "Be abstractive: do not quote or copy sentences verbatim. "
                "Do NOT include code blocks or long configuration snippets."
            )
            user = (
                "Summarize the text as 6-10 bullet points.\n"
                "- Each bullet: 3-7 words.\n"
                "- Focus on main messages and concepts.\n"
                "- Do NOT include code blocks, YAML, or copied sentences.\n"
                "- Output MUST be a Markdown bullet list where each line starts with '- '.\n"
                "- No preamble, no paragraphs.\n\n"
                f"Text:\n{context}"
            )
        elif mode == "keywords":
            sys = "You extract keywords/keyphrases for indexing."
            user = (
                "Extract 10-18 keywords/keyphrases.\n"
                "- Prefer nouns/proper nouns/short phrases.\n"
                "- Output a single comma-separated line.\n\n"
                f"Text:\n{context}"
            )
        elif mode == "summary":
            sys = (
                "You write concise summaries for browsing. "
                "Be abstractive: do not quote or copy sentences verbatim. "
                "Do NOT include code blocks or YAML."
            )
            user = (
                "Write a concise summary focusing on the main ideas.\n"
                f"- Length: <= {target_words} words.\n"
                "- Prefer abstraction over examples.\n"
                "- Do NOT copy sentences verbatim from the text.\n"
                "- Do NOT include code blocks, YAML, or long quoted snippets.\n"
                "- Output plain text (no headings).\n\n"
                f"Text:\n{context}"
            )
        else:
            # Default: detail-rich (legacy behavior)
            sys = (
                "You are a helpful assistant. "
                "Be mostly abstractive: avoid copying full sentences verbatim. "
                "Do NOT include code blocks or YAML; describe them instead."
            )
            user = (
                "Write a detailed summary of the following.\n"
                f"- Length: <= {target_words} words.\n"
                "- Prefer paraphrase over quoting.\n"
                "- Do NOT include code blocks/YAML (describe what they do).\n\n"
                f"Text:\n{context}"
            )
        return [{"role": "system", "content": sys}, {"role": "user", "content": user}]

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
    def summarize(self, context, max_tokens=500, stop_sequence=None):
        # Non-layered call uses default mode.
        return self.summarize_layer(context, layer=-1, max_tokens=max_tokens)

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
    def summarize_layer(self, context: str, *, layer: int, max_tokens: int) -> str:
        mode = self.mode_by_layer.get(int(layer), self.default_mode)
        messages = self._messages(
            context, mode=mode, layer=int(layer), max_tokens=int(max_tokens)
        )
        try:
            timer = _Timer()
            resp = self._client().chat.completions.create(
                model=self.model,
                messages=messages,
                max_completion_tokens=int(max_tokens),
            )
            log_usage(
                kind="summarize_layer",
                model=self.model,
                usage=getattr(resp, "usage", None),
                duration_s=timer.elapsed(),
                meta={
                    "layer": int(layer),
                    "mode": str(mode),
                    "max_completion_tokens": int(max_tokens),
                },
            )
            out = resp.choices[0].message.content
        except Exception as e:
            msg = str(e)
            if "max_completion_tokens" in msg or "Unsupported parameter" in msg:
                timer = _Timer()
                resp = self._client().chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=int(max_tokens),
                )
                log_usage(
                    kind="summarize_layer",
                    model=self.model,
                    usage=getattr(resp, "usage", None),
                    duration_s=timer.elapsed(),
                    meta={
                        "layer": int(layer),
                        "mode": str(mode),
                        "max_tokens": int(max_tokens),
                    },
                )
                out = resp.choices[0].message.content
            else:
                raise

        out = (out or "").strip()
        mode_l = (mode or "").strip().lower()

        # If the model hit the API length limit, the output may be truncated mid-thought.
        # Retry once with a stricter compression instruction (still under the same hard cap).
        finish_reason = (
            getattr(resp.choices[0], "finish_reason", None)
            if "resp" in locals()
            else None
        )
        if finish_reason == "length" and out:
            logging.warning(
                "[RAPTOR_SUMMARY_TRUNCATED] model=%s layer=%s mode=%s max_tokens=%s out_chars=%s",
                self.model,
                layer,
                mode_l,
                int(max_tokens),
                len(out),
            )
            if self._debug_enabled_for("truncation"):
                self._debug_log(
                    event="truncation",
                    messages=messages,
                    output=str(out or ""),
                    meta={
                        "model": self.model,
                        "layer": int(layer),
                        "mode": mode_l,
                        "max_tokens": int(max_tokens),
                        "finish_reason": finish_reason,
                    },
                )
            target_words = self._target_words(int(max_tokens))
            compress_msgs = [
                {
                    "role": "system",
                    "content": (
                        "Compress the content into a shorter abstractive summary. "
                        "Do NOT copy sentences verbatim. No code blocks/YAML."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Rewrite the source text into <= {max(20, int(target_words * 0.85))} words.\n"
                        "- Preserve the most important concepts.\n"
                        "- Plain text only.\n\n"
                        f"Source text:\n{context}"
                    ),
                },
            ]
            try:
                timer_c = _Timer()
                resp_c = self._client().chat.completions.create(
                    model=self.model,
                    messages=compress_msgs,
                    max_completion_tokens=int(max_tokens),
                )
                log_usage(
                    kind="summarize_layer_truncation_rewrite",
                    model=self.model,
                    usage=getattr(resp_c, "usage", None),
                    duration_s=timer_c.elapsed(),
                    meta={
                        "layer": int(layer),
                        "mode": mode_l,
                        "max_completion_tokens": int(max_tokens),
                    },
                )
                out_c = (resp_c.choices[0].message.content or "").strip()
                if out_c:
                    out = out_c
            except Exception:
                pass

        # Anti-copy guard: if output is highly extractive vs the provided context, do a rewrite.
        # This directly addresses the "parent node is just an excerpt of one child" failure mode.
        # Note: overlap can be low if the context is a concatenation of many children; also check for
        # obvious provenance/heading leakage, which is nearly always a sign the model copied.
        overlap = self._ngram_overlap_ratio(out, context, n=5)
        looks_like_copy = (
            (out and len(out) >= 80 and overlap >= 0.75)
            or (out.lstrip().startswith("#"))
            or ("Source:" in out[:400])
        )
        if looks_like_copy and mode_l in ("summary", "bullets", "details"):
            logging.warning(
                "[RAPTOR_SUMMARY_EXTRACTIVE_GUARD] model=%s layer=%s mode=%s overlap=%.2f max_tokens=%s out_chars=%s ctx_chars=%s",
                self.model,
                layer,
                mode_l,
                overlap,
                int(max_tokens),
                len(out),
                len(context or ""),
            )
            if self._debug_enabled_for("guard"):
                self._debug_log(
                    event="guard",
                    messages=messages,
                    output=str(out or ""),
                    meta={
                        "model": self.model,
                        "layer": int(layer),
                        "mode": mode_l,
                        "max_tokens": int(max_tokens),
                        "overlap": float(overlap),
                        "finish_reason": finish_reason,
                        "prompt_version": getattr(self, "prompt_version", "v1"),
                    },
                )
            rewrite_sys = (
                "Rewrite the content in your own words. "
                "Do NOT copy sentences verbatim from the source. "
                "Do NOT include code blocks/YAML; describe them at a high level."
            )
            if mode_l == "bullets":
                rewrite_user = (
                    "Rewrite the following source text as 6-10 bullet points.\n"
                    "- Each line MUST start with '- '.\n"
                    "- Each bullet: 3-7 words.\n"
                    "- Abstractive only (no copied sentences).\n"
                    "- No code/YAML.\n\n"
                    f"Source text:\n{context}"
                )
            elif mode_l == "summary":
                rewrite_user = (
                    "Rewrite the following source text as a concise, abstractive summary.\n"
                    "- 3-6 sentences.\n"
                    "- No headings, no code, no YAML.\n"
                    "- Do not copy sentences.\n\n"
                    f"Source text:\n{context}"
                )
            else:  # details
                rewrite_user = (
                    "Rewrite the following source text as a detailed but abstractive summary.\n"
                    "- 1-2 short paragraphs.\n"
                    "- No headings, no code, no YAML.\n"
                    "- Do not copy sentences.\n\n"
                    f"Source text:\n{context}"
                )
            rewrite_msgs = [
                {"role": "system", "content": rewrite_sys},
                {"role": "user", "content": rewrite_user},
            ]
            try:
                timer_r = _Timer()
                resp_r = self._client().chat.completions.create(
                    model=self.model,
                    messages=rewrite_msgs,
                    max_completion_tokens=int(max_tokens),
                )
                log_usage(
                    kind="summarize_layer_guard_rewrite",
                    model=self.model,
                    usage=getattr(resp_r, "usage", None),
                    duration_s=timer_r.elapsed(),
                    meta={
                        "layer": int(layer),
                        "mode": mode_l,
                        "max_completion_tokens": int(max_tokens),
                    },
                )
                out_r = (resp_r.choices[0].message.content or "").strip()
                if out_r:
                    out = out_r
                    overlap2 = self._ngram_overlap_ratio(out, context, n=5)
                    logging.info(
                        "[RAPTOR_SUMMARY_EXTRACTIVE_GUARD_OK] model=%s layer=%s mode=%s overlap_before=%.2f overlap_after=%.2f",
                        self.model,
                        layer,
                        mode_l,
                        overlap,
                        overlap2,
                    )
            except Exception:
                # Best-effort; keep original output if rewrite fails.
                logging.warning(
                    "[RAPTOR_SUMMARY_EXTRACTIVE_GUARD_FAILED] model=%s layer=%s mode=%s overlap=%.2f",
                    self.model,
                    layer,
                    mode_l,
                    overlap,
                )
                pass

        # Enforce structured formats for certain modes (best-effort).
        if mode and str(mode).strip().lower() == "bullets":
            has_bullets = any(
                line.lstrip().startswith("- ") for line in out.splitlines()
            )
            if not has_bullets:
                # One cheap rewrite pass to force bullets.
                rewrite_msgs = [
                    {
                        "role": "system",
                        "content": "Rewrite strictly as a Markdown bullet list.",
                    },
                    {
                        "role": "user",
                        "content": (
                            "Rewrite the following as 6-10 bullet points.\n"
                            "- Each line MUST start with '- '.\n"
                            "- No paragraphs.\n\n"
                            f"Text:\n{context}"
                        ),
                    },
                ]
                try:
                    timer_b = _Timer()
                    resp2 = self._client().chat.completions.create(
                        model=self.model,
                        messages=rewrite_msgs,
                        max_completion_tokens=int(max_tokens),
                    )
                    log_usage(
                        kind="summarize_layer_bullets_enforce",
                        model=self.model,
                        usage=getattr(resp2, "usage", None),
                        duration_s=timer_b.elapsed(),
                        meta={
                            "layer": int(layer),
                            "mode": mode_l,
                            "max_completion_tokens": int(max_tokens),
                        },
                    )
                    out2 = (resp2.choices[0].message.content or "").strip()
                    if out2:
                        out = out2
                except Exception:
                    pass

        return out


class CachedSummarizationModel(BaseSummarizationModel, LayerAwareSummarizationMixin):
    """
    Wrap another summarizer and store/reuse summaries in a persistent cache.
    """

    def __init__(self, model: BaseSummarizationModel, *, cache, model_id: str):
        self.model = model
        self.cache = cache
        self.model_id = model_id

    def summarize(self, context, max_tokens=150):
        # Non-layered calls use layer=-1.
        return self.summarize_layer(
            str(context or ""), layer=-1, max_tokens=int(max_tokens)
        )

    def summarize_layer(self, context: str, *, layer: int, max_tokens: int) -> str:
        from .summary_cache import SummaryCache

        key = SummaryCache.make_key(
            model_id=self.model_id,
            layer=int(layer),
            max_tokens=int(max_tokens),
            context=str(context or ""),
        )
        hit = self.cache.get(key)
        if isinstance(hit, str) and hit.strip():
            # If a cached summary looks suspiciously extractive, recompute and overwrite the cache.
            # This prevents old/stale cached summaries from reintroducing the “parent == child excerpt” issue.
            try:
                from .SummarizationModels import (
                    OpenAILayeredSummarizationModel,
                )  # self-import safe at runtime
            except Exception:
                OpenAILayeredSummarizationModel = None  # type: ignore

            txt = hit.strip()
            looks_like_copy = txt.lstrip().startswith("#") or ("Source:" in txt[:400])
            if not looks_like_copy and OpenAILayeredSummarizationModel is not None:
                # Use the same overlap heuristic if available.
                try:
                    ov = OpenAILayeredSummarizationModel._ngram_overlap_ratio(txt, context, n=5)  # type: ignore[attr-defined]
                    if ov >= 0.75 and len(txt) >= 80:
                        looks_like_copy = True
                except Exception:
                    pass

            if not looks_like_copy:
                return txt

        if hasattr(self.model, "summarize_layer"):
            out = self.model.summarize_layer(context, layer=int(layer), max_tokens=int(max_tokens))  # type: ignore[attr-defined]
        else:
            out = self.model.summarize(context, int(max_tokens))

        if isinstance(out, str) and out.strip():
            self.cache.put(key, out)
        return (out or "").strip()


class GPT3SummarizationModel(BaseSummarizationModel):
    def __init__(self, model="text-davinci-003"):
        self.model = model

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
    def summarize(self, context, max_tokens=500, stop_sequence=None):
        # NOTE: legacy model (kept for compatibility; not used by ingest scripts).
        """
        Legacy (broken) indentation block kept only for historical context.
        It is intentionally wrapped in a string literal so it is not parsed/executed:

            client = OpenAI()
        messages = [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {
                        "role": "user",
                        "content": f"Write a summary of the following, including as many key details as possible: {context}:",
                    },
        ]
        """

        client = OpenAI()
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {
                "role": "user",
                "content": f"Write a summary of the following, including as many key details as possible: {context}:",
            },
        ]

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_completion_tokens=max_tokens,
            )
            return response.choices[0].message.content
        except Exception as e:
            msg = str(e)
            if "max_completion_tokens" in msg or "Unsupported parameter" in msg:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content
            raise
