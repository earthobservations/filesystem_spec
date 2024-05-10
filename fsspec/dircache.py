import logging
import time
from collections.abc import MutableMapping
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)


class DisabledListingsCache(MutableMapping):
    def __init__(self, *args, **kwargs):
        pass

    def __getitem__(self, item):
        raise KeyError

    def __setitem__(self, key, value):
        pass

    def __delitem__(self, key):
        pass

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def clear(self):
        pass

    def __contains__(self, item):
        return False

    def __reduce__(self):
        return (DisabledListingsCache, ())


class MemoryListingsCache(MutableMapping):
    """
    Caching of directory listings, in a structure like::

        {"path0": [
            {"name": "path0/file0",
             "size": 123,
             "type": "file",
             ...
            },
            {"name": "path0/file1",
            },
            ...
            ],
         "path1": [...]
        }

    Parameters to this class control listing expiry or indeed turn
    caching off
    """

    def __init__(
        self,
        expiry_time=None,
        max_paths=None,
    ):
        """

        Parameters
        ----------
        expiry_time: int or float (optional)
            Time in seconds that a listing is considered valid. If None,
            listings do not expire.
        max_paths: int (optional)
            The number of most recent listings that are considered valid; 'recent'
            refers to when the entry was set.
        """
        self._cache = {}
        self._times = {}
        if max_paths:
            self._q = lru_cache(max_paths + 1)(lambda key: self._cache.pop(key, None))
        self._expiry_time = expiry_time
        self._max_paths = max_paths

    def __getitem__(self, item):
        if self._expiry_time is not None:
            if self._times.get(item, 0) - time.time() < -self._expiry_time:
                del self._cache[item]
        if self._max_paths:
            self._q(item)
        return self._cache[item]  # maybe raises KeyError

    def clear(self):
        self._cache.clear()

    def __len__(self):
        return len(self._cache)

    def __contains__(self, item):
        try:
            self[item]
            return True
        except KeyError:
            return False

    def __setitem__(self, key, value):
        if self._max_paths:
            self._q(key)
        self._cache[key] = value
        if self._expiry_time is not None:
            self._times[key] = time.time()

    def __delitem__(self, key):
        del self._cache[key]

    def __iter__(self):
        entries = list(self._cache)

        return (k for k in entries if k in self)

    def __reduce__(self):
        return (
            MemoryListingsCache,
            (self._expiry_time, self._max_paths),
        )


class FileListingsCache(MutableMapping):
    def __init__(
        self,
        expiry_time: Optional[int],
        directory: Optional[Path],
    ):
        """

        Parameters
        ----------
        expiry_time: int or float (optional)
            Time in seconds that a listing is considered valid. If None,
            listings do not expire.
        directory: str (optional)
            Directory path at which the listings cache file is stored. If None,
            an autogenerated path at the user folder is created.

        """
        try:
            import platformdirs
            from diskcache import Cache
        except ImportError as e:
            raise ImportError(
                "The optional dependencies ``platformdirs`` and ``diskcache`` are required for file-based dircache."
            ) from e

        if not directory:
            directory = platformdirs.user_cache_dir(appname="fsspec")
        directory = Path(directory) / "dircache" / str(expiry_time)

        try:
            directory.mkdir(exist_ok=True, parents=True)
        except OSError as e:
            logger.error(f"Directory for dircache could not be created at {directory}.")
            raise e
        else:
            logger.info(f"Dircache located at {directory}.")

        self._expiry_time = expiry_time
        self._directory = directory
        self._cache = Cache(directory=str(directory))

    def __getitem__(self, item):
        """Draw item as fileobject from cache, retry if timeout occurs"""
        return self._cache.get(key=item, read=True, retry=True)

    def clear(self):
        self._cache.clear()

    def __len__(self):
        return len(list(self._cache.iterkeys()))

    def __contains__(self, item):
        value = self._cache.get(item, retry=True)  # None, if expired
        if value:
            return True
        return False

    def __setitem__(self, key, value):
        self._cache.set(key=key, value=value, expire=self._expiry_time, retry=True)

    def __delitem__(self, key):
        del self._cache[key]

    def __iter__(self):
        return (k for k in self._cache.iterkeys() if k in self)

    def __reduce__(self):
        return (
            FileListingsCache,
            (self._expiry_time, self._directory),
        )


class CacheType(Enum):
    DISABLED = DisabledListingsCache
    MEMORY = MemoryListingsCache
    FILE = FileListingsCache


def create_listings_cache(
    cache_type: CacheType,
    expiry_time: Optional[int],
    **kwargs,
) -> Optional[Union[MemoryListingsCache, FileListingsCache]]:
    cache_map = {
        CacheType.DISABLED: DisabledListingsCache,
        CacheType.MEMORY: MemoryListingsCache,
        CacheType.FILE: FileListingsCache,
    }
    return cache_map[cache_type](expiry_time, **kwargs)
