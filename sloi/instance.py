from __future__ import annotations

import os
from pathlib import Path


class InstanceLock:
    def __init__(self, root: Path):
        path = root / "runtime" / "instance.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open("a+b")
        self.stream.seek(0)
        try:
            empty = not self.stream.read(1)
        except PermissionError as exc:
            self.stream.close()
            raise RuntimeError("SLOI уже запущен из этой папки. Закройте backend перед установкой или обновлением.") from exc
        if empty:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError):
            self.stream.close()
            raise RuntimeError("SLOI уже запущен из этой папки. Закройте backend перед установкой или обновлением.")

    def close(self):
        if self.stream.closed:
            return
        if os.name == "nt":
            import msvcrt
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
