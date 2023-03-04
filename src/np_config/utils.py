from __future__ import annotations

import contextlib
import datetime
import doctest
import logging
import os
import pathlib
import re
import socket
import sys
from typing import Any, Hashable, Mapping, MutableMapping, TypeVar

from typing_extensions import Literal
from singledispatch import singledispatch

logger = logging.getLogger(__name__)

HOSTNAME = socket.gethostname().upper()

T = TypeVar("T", bound=MutableMapping[Hashable, Any])


def merge(
    base: MutableMapping[Hashable, Any], update: Mapping[Hashable, Any]
) -> MutableMapping[Hashable, Any]:
    """
    Utility function to do a deep merge on dictionaries. `base` will be modified, so deep
    copy first if the original needs to be preserved. This is a recursive function, so
    it merges nested dicts. If a value isn't a dict in both `base` and `update` the
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
    host = host.strip("\\/ ").upper()
    path = pathlib.Path(path).as_posix().replace(":", "")
    return normalize_path(f"//{host}/{path}")


def unc_to_local(path: str | pathlib.Path) -> pathlib.Path:
    """Try to convert UNC path with drive letter to local path (for Windows).
    
    >>> unc_to_local("//W10DT713843/C/ProgramData/AIBS_MPE/MVR/data").as_posix()
    'C:/ProgramData/AIBS_MPE/MVR/data'
    
    Path with no drive letter will raise an error:
    >>> unc_to_local("//w10dtsm18306/neuropixels_data")
    Traceback (most recent call last):
     ...
    ValueError: UNC path points to a host + share name (not host + drive letter): insufficient information to construct a local path from //w10dtsm18306/neuropixels_data
    """
    path: pathlib.Path = normalize_path(path)

    if path.as_posix()[0] != "/":
        raise ValueError(f"Path must be UNC (starting with a slash): {path.as_posix()}")

    # UNC path starts with host + drive letter or share
    # Path.parts merges UNC host and share, so we need to split manually
    parts = [_ for _ in path.as_posix().split("/") if _]
    drive = parts[1].strip("$")
    if len(drive) > 1:
        raise ValueError(
            f"UNC path points to a host + share name (not host + drive letter): insufficient information to construct a local path from {path.as_posix()}"
        )
    return normalize_path(f"{drive}:/" + "/".join(parts[2:]))


def normalize_path(path: str | pathlib.Path) -> pathlib.Path:
    """Normalize a path to a pathlib.Path object, starting with `//` if a network path.
    
    >>> normalize_path("\\W10DT713843\\c/ProgramData/AIBS_MPE/MVR/data").as_posix()
    '//W10DT713843/c/ProgramData/AIBS_MPE/MVR/data'
    """
    path = str(path)
    path = path.replace("\\", "/")  # makes the next parts simpler
    if path[0] == "/" and path[1] != path[0]:
        path = "/" + path
        path.replace(":", "")
    return pathlib.Path(path)


def local_or_unc_path(host: str, path: str | pathlib.Path) -> pathlib.Path:
    """Get a path that works from a location on the host computer. 
    
    - converts a UNC path to a local path if running on the host computer specified in the
    UNC path.
    - converts a local path to a UNC path if running on a different computer.
    """
    if HOSTNAME == host:
        with contextlib.suppress(ValueError):
            _ = unc_to_local(path)
            if _.exists():
                return _
        # otherwise path is not unc
        normalized = normalize_path(
            pathlib.Path(str(path).replace("$", ":"))
        )
        if not normalized.exists():
            logger.warning("Path not found in local filesystem: %s", path)
        return normalized

    if host not in str(path):
        return local_to_unc(host, path)
    return normalize_path(path)


def rig_idx(id: str | None) -> Literal[0, 1, 2, 3, 4] | None:
    """Convert rig ID (`'NP.1'`) to valid rig index (`1`).
    
    >>> rig_idx('NP.1')
    1
    >>> rig_idx('NP1')
    1

    Also accepts bad input, if index is valid:
    >>> rig_idx('1')
    1
    >>> rig_idx(1)
    1
    """
    if id is None:
        return None
    valid_idx = (0, 1, 2, 3, 4)
    with contextlib.suppress(Exception):
        result = int(str(id))  # if idx provided instead of id
        if result in valid_idx:
            return result
    result = re.findall(fr"NP\.?([\d]+)", id.upper())
    if not result:
        return None
    result = int(result[0])
    if result not in valid_idx:
        return None
    return result


PLATFORM_JSON_TIME_FMT = "%Y%m%d%H%M%S"

@singledispatch
def normalize_time(t: str | float | int | datetime.datetime) -> str: 
    """
    A standard time format matching platform JSON files.
    
    >>> normalize_time(datetime.datetime(2023, 2, 14, 13, 30, 00))
    '20230214133000'
    >>> normalize_time(1676410200.0)
    '20230214133000'
    >>> normalize_time(1676410200)
    '20230214133000'
    >>> normalize_time('1676410200.0')
    '20230214133000'
    >>> normalize_time('1676410200')
    '20230214133000'
    >>> normalize_time('2023-02-14T13:30:00')
    '20230214133000'
    """
    return _
    
@normalize_time.register
def _(t: datetime.datetime) -> str:
    return t.strftime(PLATFORM_JSON_TIME_FMT)

@normalize_time.register
def _(t: float) -> str:
    return datetime.datetime.fromtimestamp(t).strftime(PLATFORM_JSON_TIME_FMT)

@normalize_time.register
def _(t: int) -> str:
    # can't use int | float because of future.__annotations__
    return datetime.datetime.fromtimestamp(t).strftime(PLATFORM_JSON_TIME_FMT)

@normalize_time.register
def _(t: str) -> str:
    if len(t) == 14: # already in correct format
        return datetime.datetime(int(t[:4]), *(int(t[_:_+2]) for _ in range(4, 14, 2))).strftime(PLATFORM_JSON_TIME_FMT)
    with contextlib.suppress(ValueError):
        return datetime.datetime.fromtimestamp(float(t)).strftime(PLATFORM_JSON_TIME_FMT)
    with contextlib.suppress(ValueError):
        return datetime.datetime.fromisoformat(t).strftime(PLATFORM_JSON_TIME_FMT) 
    raise ValueError(f"Unable to parse time: {t}")

if __name__ == "__main__":
    doctest.testmod()
