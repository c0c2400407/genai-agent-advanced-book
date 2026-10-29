"""GUIとCLIを同時実行しても生成リクエストを重ねないための実行ロック。"""
import os
from contextlib import contextmanager

from workshop.search import ROOT
from src.security import safe_dir


@contextmanager
def single_run():
    folder = ROOT / ".workshop"
    safe_dir(folder, ROOT)
    with (folder / "runner.lock").open("a+b") as handle:
        if handle.seek(0, 2) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("別のCLIまたはGUIで実行中です。完了を待ってから実行してください。") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
