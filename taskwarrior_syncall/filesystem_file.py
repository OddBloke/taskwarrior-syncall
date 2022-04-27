import datetime
import uuid
from pathlib import Path
from typing import Optional, Union

import xattr
from bubop.fs import FileType
from item_synchronizer.types import ID
from loguru import logger

from taskwarrior_syncall.concrete_item import ConcreteItem, ItemKey, KeyType


def _generate_id() -> str:
    return str(uuid.uuid4())


def _to_b(s: str) -> bytes:
    return bytes(s.encode("utf-8"))


def _from_b(b: bytes) -> str:
    return b.decode("utf-8")


class FilesystemFile(ConcreteItem):
    """Encode the interaction with a filesystem entity.

    This encodes a UUID for this file in the file's extended attributes. Only filesystems that
    support extended attributes are supported.

    .. note:: None of the changes to the file will be written unless you either call `.flush()`
              or you handle it via a context manager , in which change `.flush()` will be
              called automatically on `__exit__`.
    """

    _attr = "user.syncall.uuid"
    _default_ext = ".txt"

    def __init__(self, path: Union[str, Path], filetype=FileType.FILE):
        """Create a file under the given apth and using the given contents."""
        super().__init__(
            keys=(
                ItemKey("last_modified_date", KeyType.Date),
                ItemKey("contents", KeyType.String),
                ItemKey("title", KeyType.String),
            )
        )
        if not filetype is FileType.FILE:
            raise NotImplementedError("Only supporting synchronization for raw files.")

        path_ = Path(path)
        self._ext = path_.suffix if path_.suffix else self._default_ext

        self._path = path_.with_suffix(self._ext)
        self._contents: str = ""
        self._title = self._path.stem
        if self._path.is_file():
            self._contents = self._path.read_text()

        self._filetype = filetype

        # flags to check on exit --------------------------------------------------------------
        self._set_id_on_flush: bool = False
        self._set_contents_on_flush: bool = False
        self._set_title_on_flush: bool = False
        self._set_for_deletion: bool = False

        # get or assign new ID ----------------------------------------------------------------
        try:
            self._id_str = self._get_id()
        except IOError:
            self._id_str = _generate_id()
            logger.trace(
                f"File [{self._title}] doesn't have an ID yet, assigning new ID ->"
                f" {self._id_str}"
            )
            self._set_id_on_flush = True

    @property
    def root(self):
        return self._path.parent

    @root.setter
    def root(self, new_root: Path):
        self._path = new_root / self._path.name

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.flush()

    def flush(self) -> None:
        """Teardown method - call this to make changes to the file persistent."""

        # delete if it's for deletion
        if self._set_for_deletion:
            self._path.unlink()
            self._set_for_deletion = False
            return

        # flush contents ----------------------------------------------------------------------
        if self._set_contents_on_flush:
            self._set_contents_on_flush = False
            self._path.write_text(self._contents)

        # flush the title ---------------------------------------------------------------------
        if self._set_title_on_flush:
            self._set_title_on_flush = False
            self._path = self._path.rename(
                self._path.with_name(self.title).with_suffix(self._ext)
            )
            logger.trace(f"Renaming file on disk, new name -> {self._path.name}")

        # flush UUID --------------------------------------------------------------------------
        if self._set_id_on_flush:
            self._set_id_on_flush = False
            self._set_id(self._id_str)

    def _set_id(self, new_id: str) -> None:
        with self._path.open() as fd:
            xattr.setxattr(fd, _to_b(self._attr), _to_b(new_id))

    def _get_id(self) -> str:
        return self.get_id_of_path(path=self._path)

    @classmethod
    def get_id_of_path(cls, path: Path) -> ID:
        with path.open() as fd:
            return _from_b(xattr.getxattr(fd, _to_b(cls._attr)))

    def _id(self) -> Optional[ID]:
        return self._id_str

    @property
    def contents(self):
        return self._contents

    @contents.setter
    def contents(self, new_contents):
        self._contents = new_contents
        self._set_contents_on_flush = True

    @property
    def title(self):
        return self._title

    @title.setter
    def title(self, new_title):
        self._title = new_title
        self._set_title_on_flush = True

    @property
    def last_modified_date(self) -> datetime.datetime:
        # TODO Amend this.
        try:
            return datetime.datetime.fromtimestamp(self._path.stat().st_mtime)
        except FileNotFoundError:
            return datetime.datetime.utcfromtimestamp(0)

    def delete(self) -> None:
        """Mark this file for deletion."""
        self._set_for_deletion = True
