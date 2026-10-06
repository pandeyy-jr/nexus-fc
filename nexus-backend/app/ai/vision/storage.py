import asyncio
import os
import re
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISLNK, S_ISREG
from typing import Protocol
from uuid import UUID

_VIDEO_SUFFIXES = frozenset({".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"})
_STORAGE_REFERENCE = re.compile(r"^[0-9a-f]{32}\.(?:avi|m4v|mkv|mov|mp4|webm)$")


class VideoStorageError(Exception):
    """Base exception for controlled storage failures."""


class StorageConflict(VideoStorageError):
    """Raised when a generated storage key already exists."""


class StorageSizeLimitExceeded(VideoStorageError):
    """Raised when an incoming stream exceeds the configured size limit."""


class StorageObjectMissing(VideoStorageError):
    """Raised when a generated storage reference has no regular file."""


@dataclass(frozen=True)
class StoredVideo:
    storage_reference: str
    file_size_bytes: int


class VideoStorage(Protocol):
    def resolve(self, storage_reference: str) -> Path: ...

    async def store(
        self,
        source_id: UUID,
        suffix: str,
        chunks: AsyncIterator[bytes],
        max_size_bytes: int,
    ) -> StoredVideo: ...

    async def delete(self, storage_reference: str) -> None: ...


class LocalVideoStorage:
    """Store videos under an application-owned directory using opaque keys."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve(self, storage_reference: str) -> Path:
        if not _STORAGE_REFERENCE.fullmatch(storage_reference):
            raise StorageObjectMissing
        try:
            root = self.root.resolve(strict=True)
            target = root / storage_reference
            details = target.lstat()
        except OSError as exc:
            raise StorageObjectMissing from exc
        if S_ISLNK(details.st_mode) or not S_ISREG(details.st_mode):
            raise StorageObjectMissing
        if target.parent != root:
            raise StorageObjectMissing
        return target

    async def store(
        self,
        source_id: UUID,
        suffix: str,
        chunks: AsyncIterator[bytes],
        max_size_bytes: int,
    ) -> StoredVideo:
        if suffix not in _VIDEO_SUFFIXES:
            raise ValueError("Unsupported storage suffix")

        await asyncio.to_thread(
            self.root.mkdir, parents=True, exist_ok=True, mode=0o700
        )
        root = await asyncio.to_thread(self.root.resolve, True)
        storage_reference = f"{source_id.hex}{suffix}"
        target = root / storage_reference
        file_descriptor, temporary_name = await asyncio.to_thread(
            tempfile.mkstemp, prefix=".video-", suffix=".part", dir=root
        )
        temporary_path = Path(temporary_name)
        file = os.fdopen(file_descriptor, "wb")
        file_size = 0
        linked = False
        try:
            async for chunk in chunks:
                file_size += len(chunk)
                if file_size > max_size_bytes:
                    raise StorageSizeLimitExceeded
                await asyncio.to_thread(file.write, chunk)
            if file_size == 0:
                raise ValueError("Video body is empty")
            await asyncio.to_thread(file.flush)
            await asyncio.to_thread(os.fsync, file.fileno())
            await asyncio.to_thread(file.close)
            try:
                await asyncio.to_thread(os.link, temporary_path, target)
            except FileExistsError as exc:
                raise StorageConflict from exc
            linked = True
            await asyncio.to_thread(temporary_path.unlink)
            return StoredVideo(storage_reference, file_size)
        except BaseException:
            if not file.closed:
                await asyncio.to_thread(file.close)
            await asyncio.to_thread(temporary_path.unlink, missing_ok=True)
            if linked:
                await asyncio.to_thread(target.unlink, missing_ok=True)
            raise

    async def delete(self, storage_reference: str) -> None:
        if not _STORAGE_REFERENCE.fullmatch(storage_reference):
            raise ValueError("Invalid storage reference")
        root = await asyncio.to_thread(self.root.resolve, True)
        target = root / storage_reference
        if target.parent != root:
            raise ValueError("Invalid storage reference")
        await asyncio.to_thread(target.unlink, missing_ok=True)
