"""Small filesystem helpers used by resumable ingestion writers."""

from pathlib import Path
import time


def replace_with_retry(source: Path, destination: Path) -> None:
    """Publish a prepared file despite brief Windows reader/scanner locks.

    Retry only the atomic rename, never the provider request or serialization.
    Persistent permission failures still propagate, leaving the prepared file.
    """
    for attempt in range(8):
        try:
            source.replace(destination)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(min(0.1 * 2 ** attempt, 1.0))
