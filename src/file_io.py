"""Shared atomic replacement. Callers own serialization, validation and recovery."""
import os
from pathlib import Path
import tempfile


def atomic_write(path, content):
    """Write bytes beside the destination, flush, then atomically replace it.

    Until replacement succeeds the old file is untouched. Errors propagate to
    the caller; an unsuccessful temporary file is removed. This intentionally
    does not implement exclusive migration, backup rotation or schema changes.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
