import os
import sys
import types

import pytest

from app.jobs import cloud_sync


def test_reports_nothing_for_missing_or_local_trees(tmp_path):
    assert cloud_sync.first_offloaded_file(tmp_path / 'missing') is None
    (tmp_path / 'nested').mkdir()
    (tmp_path / 'nested' / 'local.js').write_text('local')
    assert cloud_sync.first_offloaded_file(tmp_path) is None


@pytest.mark.skipif(sys.platform != 'darwin', reason='file provider placeholders exist only on macOS')
def test_detects_dataless_placeholder_without_reading_it(tmp_path, monkeypatch):
    nested = tmp_path / 'nested'
    nested.mkdir()
    placeholder = nested / 'evicted.js'
    placeholder.write_text('')
    real_scandir = os.scandir

    class Entry:
        def __init__(self, entry):
            self.entry, self.path = entry, entry.path

        def stat(self, follow_symlinks=True):
            info = self.entry.stat(follow_symlinks=follow_symlinks)
            if self.path == str(placeholder):
                return types.SimpleNamespace(st_mode=info.st_mode, st_flags=cloud_sync.SF_DATALESS)
            return info

    monkeypatch.setattr(cloud_sync.os, 'scandir', lambda path: [Entry(e) for e in real_scandir(path)])
    assert cloud_sync.first_offloaded_file(tmp_path) == placeholder


@pytest.mark.skipif(sys.platform != 'darwin', reason='file provider attributes exist only on macOS')
def test_marks_directory_as_excluded_from_sync(tmp_path):
    import subprocess
    cloud_sync.exclude_from_cloud_sync(tmp_path)
    attributes = subprocess.run(['xattr', str(tmp_path)], capture_output=True, text=True).stdout
    assert cloud_sync.IGNORE_ATTRIBUTE in attributes
