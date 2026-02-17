import json
import re
import threading
from abc import ABC, abstractmethod
from typing import List, Optional

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_random_exponential

from .usage_log import _Timer, log_usage


class BaseKeywordModel(ABC):
    @abstractmethod
    def extract_keywords(self, text: str, *, max_keywords: int = 12) -> List[str]:
        pass


def _normalize_keywords(xs: List[str], *, max_keywords: int) -> List[str]:
    out: List[str] = []
    seen = set()
    for x in xs:
        if not isinstance(x, str):
            continue
        k = x.strip()
        if not k:
            continue
        # Keep keywords compact
        if len(k) > 80:
            k = k[:80].rstrip() + "…"
        key = k.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(k)
        if len(out) >= max_keywords:
            break
    return out


_JSON_ARRAY_RE = re.compile(r"\\[[\\s\\S]*\\]")


class OpenAIKeywordModel(BaseKeywordModel):
    def __init__(self, model: str = "gpt-5.2", *, client: Optional[OpenAI] = None):
        self.model = model
        # OpenAI client objects are not guaranteed thread-safe; use one per thread unless injected.
        self._client_override = client
        self._tls = threading.local()

    def _client(self) -> OpenAI:
        if self._client_override is not None:
            return self._client_override
        c = getattr(self._tls, "client", None)
        if c is None:
            c = OpenAI()
            self._tls.client = c
        return c

    @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(10))
    def extract_keywords(self, text: str, *, max_keywords: int = 12) -> List[str]:
        t = (text or "").strip()
        if not t:
            return []

        timer = _Timer()
        messages = [
            {
                "role": "system",
                "content": (
                    "Extract keywords/keyphrases from the provided text. "
                    "Return ONLY a JSON array of strings. "
                    "Prefer nouns/proper nouns/short phrases. No sentences."
                ),
            },
            {
                "role": "user",
                "content": (f"Max keywords: {max_keywords}\\n" "Text:\\n" f"{t}"),
            },
        ]

        resp = self._client().chat.completions.create(
            model=self.model,
            messages=messages,
            max_completion_tokens=200,
        )
        log_usage(
            kind="keywords",
            model=self.model,
            usage=getattr(resp, "usage", None),
            duration_s=timer.elapsed(),
            meta={"max_keywords": int(max_keywords)},
        )
        raw = (resp.choices[0].message.content or "").strip()
        if not raw:
            return []

        # Prefer strict JSON array output, but be robust.
        m = _JSON_ARRAY_RE.search(raw)
        candidate = m.group(0) if m else raw
        try:
            data = json.loads(candidate)
            if isinstance(data, list):
                return _normalize_keywords(
                    [str(x) for x in data], max_keywords=max_keywords
                )
        except Exception:
            pass

        # Fallback: split lines/commas
        parts = re.split(r"[\\n,;]+", raw)
        return _normalize_keywords(parts, max_keywords=max_keywords)


class SimpleKeywordModel(BaseKeywordModel):
    """
    Offline fallback: crude keyword extraction by frequency of "words".
    """

    def extract_keywords(self, text: str, *, max_keywords: int = 12) -> List[str]:
        t = (text or "").lower()
        words = re.findall(r"[a-z][a-z0-9\\-_/]{2,}", t)
        stop = {
            "kubernetes",
            "cluster",
            "pod",
            "pods",
            "node",
            "nodes",
            "container",
            "containers",
            "the",
            "and",
            "for",
            "with",
            "that",
            "this",
            "are",
            "you",
            "your",
            "can",
            "use",
            "used",
        }
        freq = {}
        for w in words:
            if w in stop:
                continue
            freq[w] = freq.get(w, 0) + 1
        ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
        return _normalize_keywords([w for w, _ in ranked], max_keywords=max_keywords)
