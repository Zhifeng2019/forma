"""Trusted launcher that applies limits before executing a generated application."""

import os
from pathlib import Path
import resource
import sys


def apply_limit(limit: int, requested: int) -> None:
    _soft, hard = resource.getrlimit(limit)
    target = requested if hard < 0 else min(requested, hard)
    # macOS rejects lowering the hard limit beneath the inherited soft limit.
    # Lower the soft limit first, then seal both at the child-specific ceiling.
    resource.setrlimit(limit, (target, hard))
    resource.setrlimit(limit, (target, target))


def main() -> None:
    memory_mb = int(sys.argv[1])
    source_dir = str(Path(sys.argv[2]).resolve())
    port = int(sys.argv[3])
    try:
        apply_limit(resource.RLIMIT_AS, memory_mb * 1024 * 1024)
    except ValueError:
        if sys.platform != 'darwin':
            raise
        print('Runtime note: memory rlimit is unsupported on this macOS host; continuing without it (non-fatal).',
              file=sys.stderr, flush=True)
    apply_limit(resource.RLIMIT_FSIZE, 64 * 1024 * 1024)
    apply_limit(resource.RLIMIT_NOFILE, 256)
    command = [
        sys.executable, '-m', 'uvicorn', 'main:app',
        '--host', '127.0.0.1', '--port', str(port), '--app-dir', source_dir,
        '--lifespan', 'on', '--timeout-keep-alive', '5', '--limit-concurrency', '50',
    ]
    os.execve(sys.executable, command, os.environ)


if __name__ == '__main__':
    main()
