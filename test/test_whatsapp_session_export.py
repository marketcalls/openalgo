"""The periodic WhatsApp session save leaves the client's own files alone.

wars 0.1.4's ``export_session()`` copies the live session file with Python's
sqlite3 while the client holds it open through the SQLite built into wars. In
one process the two libraries share file locks, so closing the Python copy
deleted the write-ahead log and its index from under the client. The client
kept writing into deleted files: every later save missed its writes, and
within the hour its saves and sends failed with "disk I/O error".

The save now copies the file from a separate process. These tests hold the
session open in another process, standing in for the client, and check that
a copy taken while it is open sees writes still in its log and leaves the log
and index where they are. The defect itself needs the two SQLite libraries of
the real client in one process, so it cannot be reproduced here.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import services.whatsapp_bot_service as wbs

# Opens the session in WAL mode, writes a row that stays in the log, and holds
# the connection open until told to stop, as the running client does.
_HOLDER = """
import sqlite3, sys
db = sqlite3.connect(sys.argv[1], isolation_level=None)
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA wal_autocheckpoint=0")
db.execute("CREATE TABLE IF NOT EXISTS device (k TEXT, v TEXT)")
db.execute("INSERT INTO device VALUES ('key', 'only-in-the-log')")
print("ready", flush=True)
sys.stdin.read()
db.close()
"""


class FakeInner:
    def __init__(self):
        self.flushes = 0

    def flush(self):
        self.flushes += 1


class FileClient:
    """The attributes of a wars 0.1.4 client the save reads, and nothing else."""

    def __init__(self, path: str):
        self._db_path = path
        self._inner = FakeInner()

    def export_session(self):
        raise AssertionError("the in-process export must not run for a file-backed client")


@pytest.fixture
def held_session(tmp_path):
    path = tmp_path / "wars_session_test.db"
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "ready"
        yield path
    finally:
        holder.communicate("", timeout=10)


def _rows(blob: bytes) -> list:
    fd, path = tempfile.mkstemp(suffix=".db")
    with open(fd, "wb") as f:
        f.write(blob)
    try:
        db = sqlite3.connect(path)
        try:
            return db.execute("SELECT k, v FROM device").fetchall()
        finally:
            db.close()
    finally:
        Path(path).unlink()


def test_copy_includes_writes_still_in_the_log(held_session):
    client = FileClient(str(held_session))

    blob = wbs._export_live_session(client)

    assert client._inner.flushes == 1
    assert wbs._is_session_snapshot(blob)
    assert _rows(blob) == [("key", "only-in-the-log")]


def test_copy_leaves_the_log_and_its_index_in_place(held_session):
    wal = Path(f"{held_session}-wal")
    shm = Path(f"{held_session}-shm")
    assert wal.exists() and shm.exists()

    wbs._export_live_session(FileClient(str(held_session)))

    assert wal.exists() and wal.stat().st_size > 0
    assert shm.exists()


def test_failed_copy_raises_and_leaves_no_dump(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    missing = tmp_path / "no_such_dir" / "session.db"

    with pytest.raises(RuntimeError, match="session copy exited"):
        wbs._export_live_session(FileClient(str(missing)))

    assert not list(tmp_path.glob("openalgo_wa_dump_*"))


def test_client_without_a_session_file_exports_itself():
    class Double:
        def export_session(self):
            return b"exported"

    assert wbs._export_live_session(Double()) == b"exported"
