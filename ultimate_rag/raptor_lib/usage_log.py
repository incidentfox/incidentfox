from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

from .costing import estimate_cost_usd

_LOCK = threading.Lock()
_BUDGET_LOCK = threading.Lock()
_BUDGET_TOTAL_USD = 0.0


def log_usage(
    *,
    kind: str,
    model: str,
    usage: Optional[object] = None,
    duration_s: Optional[float] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Best-effort JSONL usage logger for OpenAI calls.

    Enabled only when env var RAPTOR_USAGE_LOG_PATH is set.

    We intentionally keep this lightweight / non-fatal:
    - If logging fails, we do nothing.
    - If `usage` is an OpenAI usage object, we try to pull prompt/completion/total tokens.
    """
    path = os.environ.get("RAPTOR_USAGE_LOG_PATH", "").strip()
    if not path:
        return

    rec: Dict[str, Any] = {
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "kind": str(kind),
        "model": str(model),
    }
    if duration_s is not None:
        try:
            rec["duration_s"] = float(duration_s)
        except Exception:
            pass
    if meta:
        try:
            rec["meta"] = meta
        except Exception:
            pass

    # Extract usage fields if present
    if usage is not None:
        try:
            rec["prompt_tokens"] = int(getattr(usage, "prompt_tokens", 0) or 0)
            rec["completion_tokens"] = int(getattr(usage, "completion_tokens", 0) or 0)
            rec["total_tokens"] = int(getattr(usage, "total_tokens", 0) or 0)
        except Exception:
            # Some SDK versions use dict-like usage
            try:
                u = usage  # type: ignore[assignment]
                rec["prompt_tokens"] = int(u.get("prompt_tokens", 0) or 0)
                rec["completion_tokens"] = int(u.get("completion_tokens", 0) or 0)
                rec["total_tokens"] = int(u.get("total_tokens", 0) or 0)
            except Exception:
                pass

    # Append JSONL
    try:
        line = json.dumps(rec, ensure_ascii=False)
        with _LOCK:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        return

    # Optional budget guard (best-effort):
    # - Enabled when RAPTOR_BUDGET_USD is set to a positive float
    # - Enforced only when RAPTOR_ENFORCE_BUDGET=1 (so default behavior remains non-fatal)
    try:
        budget_raw = os.environ.get("RAPTOR_BUDGET_USD", "").strip()
        enforce = os.environ.get("RAPTOR_ENFORCE_BUDGET", "").strip() in (
            "1",
            "true",
            "True",
        )
        if budget_raw and enforce:
            budget = float(budget_raw)
            if budget > 0:
                pt = int(rec.get("prompt_tokens", 0) or 0)
                ct = int(rec.get("completion_tokens", 0) or 0)
                est = estimate_cost_usd(
                    model=str(model), prompt_tokens=pt, completion_tokens=ct
                )
                if est > 0:
                    global _BUDGET_TOTAL_USD
                    with _BUDGET_LOCK:
                        _BUDGET_TOTAL_USD += float(est)
                        if _BUDGET_TOTAL_USD > budget:
                            raise RuntimeError(
                                f"[RAPTOR_BUDGET] exceeded: total_est_usd={_BUDGET_TOTAL_USD:.2f} > budget_usd={budget:.2f}"
                            )
    except RuntimeError:
        # Intentionally propagate to stop long-running builds when budget is exceeded.
        raise
    except Exception:
        # Budgeting is best-effort; don't break runs due to parsing issues.
        return


class _Timer:
    def __init__(self) -> None:
        self.t0 = time.time()

    def elapsed(self) -> float:
        return float(time.time() - self.t0)
