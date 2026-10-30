"""Idempotent filesystem cleanup for attempt-owned build and runtime paths."""

import errno
from pathlib import Path
import shutil
import time


def remove_tree(path: Path, attempts: int = 4) -> None:
    """Retry transient directory races without hiding persistent filesystem errors."""
    if attempts < 1:
        raise ValueError('Cleanup attempts must be positive')
    for attempt in range(attempts):
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            elif path.exists() or path.is_symlink():
                path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            transient = exc.errno in {errno.ENOTEMPTY, errno.EBUSY}
            if not transient or attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
