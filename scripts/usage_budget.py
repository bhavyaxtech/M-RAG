"""Opt-in, persistent USD estimate guard for ingestion and the new collection.

This is not an Azure billing cap. Reservations use conservative token bounds;
failed/unknown-usage calls keep their reservation, including across restarts.
The ledger must not be deleted to resume a run. Prices exclude tax/hosting.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from threading import RLock

from scripts.file_io import replace_with_retry


# USD per million tokens, Standard Global. Sol uses the non-promotional rate.
PRICES = {"embedding": (0.143, 0), "luna": (0.20, 1.20), "terra": (2, 12), "sol": (5, 30)}
MAX_OUTPUT_TOKENS = 16384
CURRENT_BUDGET = ContextVar("api_usage_budget", default=None)


class BudgetExceeded(RuntimeError):
    pass


class UsageBudget:
    def __init__(self, path: Path, limit_usd: float):
        if not math.isfinite(limit_usd) or not 0 < limit_usd <= 30:
            raise ValueError("Budget must be positive and at most $30 USD")
        self._lock = RLock()
        self.path = path
        self.limit = limit_usd
        self.rows = []
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.limit = min(limit_usd, float(saved["limit_usd"]))
            self.rows = saved["calls"]
            for row in self.rows:
                cost = row["charged_estimate_usd"]
                if not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
                    raise ValueError("Invalid budget ledger; refusing paid calls")

    def _spent_unlocked(self):
        return sum(row["charged_estimate_usd"] for row in self.rows)

    @property
    def spent(self):
        with self._lock:
            return self._spent_unlocked()

    def _save_unlocked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "limit_usd": self.limit, "estimated_spent_usd": self._spent_unlocked(),
            "prices_usd_per_million": PRICES, "calls": self.rows,
        }, indent=2) + "\n", encoding="utf-8")
        replace_with_retry(temporary, self.path)

    def save(self):
        with self._lock:
            self._save_unlocked()

    def reserve(self, model: str, deployment: str, text: str, image_count: int = 0):
        input_rate, output_rate = PRICES[model]
        # UTF-8 bytes bound text tokens conservatively. A million tokens per
        # attached image deliberately over-reserves instead of guessing tiling.
        input_bound = len(text.encode("utf-8")) + 256 + image_count * 1_000_000
        output_bound = 0 if model == "embedding" else MAX_OUTPUT_TOKENS
        amount = (input_bound * input_rate + output_bound * output_rate) / 1_000_000
        with self._lock:
            spent = self._spent_unlocked()
            if spent + amount > self.limit:
                raise BudgetExceeded(
                    f"Paid processing paused: ${spent:.4f} recorded/reserved; "
                    f"next call reserves ${amount:.4f}; ceiling ${self.limit:.2f}."
                )
            row = {
                "time": datetime.now(timezone.utc).isoformat(), "role": model,
                "deployment": deployment, "status": "reserved_or_unknown",
                "charged_estimate_usd": amount,
            }
            self.rows.append(row)
            self._save_unlocked()
            return row

    def settle(self, row, usage, response_model):
        with self._lock:
            if usage is None:
                return  # An interrupted or unreported call retains its reservation.
            prompt = getattr(usage, "prompt_tokens", None)
            completion = getattr(usage, "completion_tokens", 0)
            if not isinstance(prompt, int) or prompt < 0 or not isinstance(completion, int) or completion < 0:
                return
            input_rate, output_rate = PRICES[row["role"]]
            row.update(
                status="usage_reported", prompt_tokens=prompt, completion_tokens=completion,
                response_model=response_model,
                charged_estimate_usd=(prompt * input_rate + completion * output_rate) / 1_000_000,
            )
            self._save_unlocked()


@contextmanager
def api_budget(path: Path, limit_usd: float = 30):
    """One process owns the ledger at a time; OS releases its lock on a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a+b") as lock:
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        import os
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        budget = UsageBudget(path, limit_usd)
        token = CURRENT_BUDGET.set(budget)
        try:
            yield budget
        finally:
            CURRENT_BUDGET.reset(token)
