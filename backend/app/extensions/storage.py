"""存储扩展接口：V1 只使用本地文件；S3 实现以后通过此接口接入。"""

from typing import Protocol
from pathlib import Path
import os


class ImageStorage(Protocol):
    def put(self, key: str, data: bytes) -> str: ...
    def read(self, key: str) -> bytes: ...


class LocalImageStorage:
    def __init__(self, root: str):
        self.root = Path(root)

    def put(self, key: str, data: bytes) -> str:
        if "/" in key or ".." in key:
            raise ValueError("invalid storage key")
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / key
        temp = path.with_suffix(".tmp")
        temp.write_bytes(data)
        os.replace(temp, path)
        return str(path)

    def read(self, key: str) -> bytes:
        if "/" in key or ".." in key:
            raise ValueError("invalid storage key")
        return (self.root / key).read_bytes()
