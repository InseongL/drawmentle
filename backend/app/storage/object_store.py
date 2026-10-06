"""Private object store for collected drawings (docs/database-schema-v1.md §5). Never served publicly.

Keys are chosen by the server. Temporary uploads live under `tmp/`; checked originals are copied to
`verified/<sample_id>/<sha256>.json` with `create_only`, so a late or repeated upload can never overwrite them.
A remote store (S3-compatible, presigned URLs) can implement the same interface later.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


class ObjectExists(Exception):
    pass


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, *, create_only: bool = False) -> None: ...
    def get(self, key: str) -> bytes | None: ...
    def delete(self, key: str) -> bool: ...
    def list(self, prefix: str) -> list[str]: ...


class LocalObjectStore:
    """Files under one root directory. Writes go to a temp file and are renamed, so readers never see half a file."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents or ".." in key.split("/"):
            raise ValueError(f"object key escapes the store: {key}")
        return path

    def put(self, key: str, data: bytes, *, create_only: bool = False) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if create_only and path.exists():
            raise ObjectExists(key)
        part = path.with_name(path.name + f".{os.getpid()}.part")
        part.write_bytes(data)
        if create_only:
            try:
                os.link(part, path)  # atomic create-only on the same volume
            except FileExistsError:
                raise ObjectExists(key) from None
            finally:
                part.unlink(missing_ok=True)
        else:
            os.replace(part, path)

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.is_file() else None

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if path.is_file():
            path.unlink()
            return True
        return False

    def list(self, prefix: str) -> list[str]:
        base = self._path(prefix) if prefix else self.root
        if not base.exists():
            return []
        return sorted(p.relative_to(self.root).as_posix() for p in base.rglob("*")
                      if p.is_file() and not p.name.endswith(".part"))


def open_store(artifact_root: Path, backend: str, root: str) -> ObjectStore:
    if backend == "local":
        return LocalObjectStore(Path(artifact_root) / root)
    raise ValueError(f"unsupported object store backend: {backend}")
