"""Keep regenerable build state out of macOS cloud sync (iCloud Drive and other file providers).

A file provider may evict file contents and leave a dataless placeholder. Reading one blocks until the
provider downloads it, which can stall Node builds and installs until they hit their timeout.
"""

import os
from pathlib import Path
import stat
import subprocess
import sys

SF_DATALESS = getattr(stat, 'SF_DATALESS', 0x40000000)
IGNORE_ATTRIBUTE = 'com.apple.fileprovider.ignore#P'


def first_offloaded_file(root: Path) -> Path | None:
    """Return one evicted file below root without reading any file contents."""
    if sys.platform != 'darwin' or not root.is_dir():
        return None
    pending = [root]
    while pending:
        try:
            entries = list(os.scandir(pending.pop()))
        except OSError:
            continue
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if getattr(info, 'st_flags', 0) & SF_DATALESS:
                return Path(entry.path)
            if stat.S_ISDIR(info.st_mode):
                pending.append(Path(entry.path))
    return None


def exclude_from_cloud_sync(path: Path) -> None:
    """Ask macOS file providers not to sync or evict path; harmless elsewhere."""
    if sys.platform != 'darwin' or not path.exists():
        return
    try:
        subprocess.run(
            ['xattr', '-w', IGNORE_ATTRIBUTE, '1', str(path)],
            capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass
