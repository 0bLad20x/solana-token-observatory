from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


# Windows may temporarily deny os.replace() when Defender/indexers/editors have
# the target open without FILE_SHARE_DELETE. Retrying preserves the atomic-write
# contract without falling back to a corruptible in-place write.
_ATOMIC_REPLACE_DELAYS_SECONDS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 2.0)
_WINDOWS_TRANSIENT_REPLACE_ERRORS = {5, 32}  # access denied / sharing violation


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _replace_with_retry(tmp: Path, path: Path) -> None:
    attempts = len(_ATOMIC_REPLACE_DELAYS_SECONDS) + 1
    for attempt in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            winerror = getattr(exc, "winerror", None)
            transient = os.name != "nt" or winerror in _WINDOWS_TRANSIENT_REPLACE_ERRORS
            if not transient or attempt == attempts - 1:
                raise RuntimeError(
                    f"Atomic replace fehlgeschlagen: {tmp} -> {path}. "
                    "Unter Windows ist die Zieldatei wahrscheinlich durch einen "
                    "Editor, Virenscanner oder einen zweiten Prozess gesperrt."
                ) from exc
            time.sleep(_ATOMIC_REPLACE_DELAYS_SECONDS[attempt])
        except OSError as exc:
            winerror = getattr(exc, "winerror", None)
            if (
                os.name != "nt"
                or winerror not in _WINDOWS_TRANSIENT_REPLACE_ERRORS
                or attempt == attempts - 1
            ):
                raise
            time.sleep(_ATOMIC_REPLACE_DELAYS_SECONDS[attempt])


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    # A unique sibling avoids two writers colliding on the old fixed `.tmp`
    # filename. The temp file must stay on the same filesystem so os.replace()
    # remains atomic.
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(_jsonable(payload), handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp, path)
    finally:
        # On success tmp no longer exists. On failure remove best-effort so a
        # transient Windows lock cannot litter the data directory indefinitely.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def append_jsonl(path: Path, records: list[dict]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(_jsonable(record), ensure_ascii=False) + "\n")
        handle.flush()