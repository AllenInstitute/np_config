from __future__ import annotations

import contextlib
import doctest
import logging
import os
import pathlib
import socket
import sys
from typing import Any, Hashable, Mapping, MutableMapping, TypeVar

logger = logging.getLogger(__name__)

HOSTNAME = socket.gethostname().upper()

T = TypeVar("T", bound=MutableMapping[Hashable, Any])

def merge(base: MutableMapping[Hashable, Any], update: Mapping[Hashable, Any]) -> MutableMapping[Hashable, Any]:
    """
    Utility function to do a deep merge on dictionaries. `base` will be modified, so deep
    copy first if the original needs to be preserved. This is a recursive function, so
    it merges nested dicts. If a value isn't a dict in both `base` and `merge` the
    values won't be merged: the value from `update` will override that of `base`.
    
    From mpeconfig.
    
    >>> merge({0: {'a': False}, 1: False}, {0: {'a': True, 'b': True}, 1: True})
    {0: {'a': True, 'b': True}, 1: True}
    """
    for key, value in update.items():
        if isinstance(value, Mapping):
            if key not in base:
                base[key] = type(value)()  # For subclasses of dict
            merge(base[key], update[key])
        else:
            base[key] = value
    return base

def local_to_unc(host: str, path: str | pathlib.Path) -> pathlib.Path:
    """Generate a UNC path (for Windows) from host + local path.
    
    >>> local_to_unc("W10DT713843", pathlib.Path("C:\\ProgramData\\AIBS_MPE\\MVR\\data")).as_posix()
    '//W10DT713843/C/ProgramData/AIBS_MPE/MVR/data'
    
    >>> local_to_unc("W10DT713843", "C$/ProgramData/AIBS_MPE/MVR/data").as_posix()
    '//W10DT713843/C$/ProgramData/AIBS_MPE/MVR/data'
    """
    host = host.strip('\\/ ').upper()
    path = pathlib.Path(path).as_posix().replace(':', '')
    return normalize_path(f'//{host}/{path}')


def unc_to_local(path: str | pathlib.Path) -> pathlib.Path:
    """Try to convert UNC path with drive letter to local path (for Windows).
    
    >>> unc_to_local("//W10DT713843/C/ProgramData/AIBS_MPE/MVR/data").as_posix()
    'C:/ProgramData/AIBS_MPE/MVR/data'
    
    Path with no drive letter will raise an error:
    >>> unc_to_local("//w10dtsm18306/neuropixels_data")
    Traceback (most recent call last):
     ...
    ValueError: UNC path points to a host + share name (not host + drive letter): insufficient information to construct a local path from //w10dtsm18306/neuropixels_data/
    """
    path: pathlib.Path = normalize_path(path)
    
    if path.as_posix()[0] != '/':
        raise ValueError(f"Path must be UNC (starting with a slash): {path.as_posix()}")
    
    # UNC path starts with host + drive letter or share
    # Path.parts merges UNC host and share, so we need to split manually
    parts = [_ for _ in path.as_posix().split('/') if _]
    drive = parts[1].strip('$')
    if len(drive) > 1:
        raise ValueError(f"UNC path points to a host + share name (not host + drive letter): insufficient information to construct a local path from {path.as_posix()}")
    return normalize_path(f'{drive}:/' + '/'.join(parts[2:]))

def normalize_path(path: str | pathlib.Path) -> pathlib.Path:
    """Normalize a path to a pathlib.Path object, starting with `//` if a network path.
    
    >>> normalize_path("\\W10DT713843\\c/ProgramData/AIBS_MPE/MVR/data").as_posix()
    '//W10DT713843/c/ProgramData/AIBS_MPE/MVR/data'
    """
    path = str(path)
    path = path.replace('\\', '/') # makes the next parts simpler
    if path[0] == '/' and path[1] != path[0]:
        path = '/' + path
        path.replace(':', '')
    return pathlib.Path(path)

def local_or_unc_path(host: str, path: str | pathlib.Path) -> pathlib.Path:
    "Convert a UNC path to a local path if running on the host computer specified in the UNC path."
    if HOSTNAME == host:
        with contextlib.suppress(ValueError):
            _ = unc_to_local(path)
            if _.exists():
                return _
        for attempt in (
            pathlib.Path(path),
            pathlib.Path(str(path).replace('$', ':')),
        ): 
            normalized = normalize_path(attempt)
            if not normalized.exists():
                logger.warning("Path not found in local filesystem: %s", path)
            return normalized

    if host not in str(path):
        return local_to_unc(host, path)
    return normalize_path(path)
    
if __name__ == "__main__":
    doctest.testmod()