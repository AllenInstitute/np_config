from __future__ import annotations

import atexit
import collections
import contextlib
import datetime
import itertools
import json
import logging
import pathlib
import platform
import subprocess
import sys
import threading
from typing import Any, Generator, Mapping

import appdirs
import yaml
from kazoo.client import KazooClient

# TODO use local backup for ZK if server unavailable

logging.getLogger('kazoo.client').setLevel('WARNING')
logger = logging.getLogger(__name__)

# preserve order of keys in dict
yaml.add_representer(
    dict,
    lambda self, data: yaml.representer.SafeRepresenter.represent_dict(
        self, data.items()
    ),
)

ZK_HOST_PORT: str = "eng-mindscope:2181"
MINDSCOPE_SERVER: str = "eng-mindscope.corp.alleninstitute.org"

ROOT_DIR: pathlib.Path = pathlib.Path(__file__).absolute().parent.parent
LOCAL_DATA_DIR = pathlib.Path(appdirs.site_data_dir("np_config", "np"))

LOCAL_ZK_BACKUP_FILE = LOCAL_DATA_DIR / "zk_backup.yaml"
"File for keeping a full backup of Zookeeper configs."

session_start_time = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
zk_record = (
    LOCAL_DATA_DIR / "config_logs" / f"zk_config-{pathlib.Path().cwd().name}.yaml"
)
SESSION_ZK_RECORD_FILE = zk_record.with_suffix(
    f".{session_start_time}{zk_record.suffix}"
)  # . is used later, don't change
"File for keeping a record of configs accessed from ZK during the current session."

SESSION_ZK_RECORD: "RecordedZK"  # created after class definition


def is_connected(host: str = MINDSCOPE_SERVER) -> bool:
    "Use OS's `ping` cmd to check if `host` is connected."
    command = ["ping", "-n" if "win" in sys.platform else "-c", "1", host]
    try:
        return subprocess.call(command, stdout=subprocess.PIPE, timeout=0.1) == 0
    except subprocess.TimeoutExpired:
        return False


def recorded_zk_config(**kwargs) -> "RecordedZK":
    return RecordedZK(record_file=SESSION_ZK_RECORD_FILE, **kwargs)


def cleanup_zk_records() -> None:
    "Remove current session zk record if it matches previous records, so we maintain config diffs only."
    path = SESSION_ZK_RECORD_FILE.parent

    def pairwise(iterable):
        "pairwise('ABCDEFG') --> AB BC CD DE EF FG"
        # itertools version not available in <3.10
        a, b = itertools.tee(iterable)
        next(b, None)
        return zip(a, b)

    for _, project_records in itertools.groupby(
        path.glob("*"), key=lambda f: f.stem.split(".")[0]
    ):
        for pair in pairwise(
            sorted(project_records, key=lambda f: f.stat().st_ctime, reverse=True)
        ):
            if pair[0].read_bytes() == pair[1].read_bytes():
                logger.debug(
                    f"Removing un-changed zk record: {pair[0].stem.split('.')[0]}"
                )
                with contextlib.suppress(Exception):
                    pair[0].unlink()
            break  # only compare against the next most recent record


atexit.register(cleanup_zk_records)


def from_zk(path: str, **kwargs) -> dict[Any, Any]:
    "Access eng-mindscope Zookeeper, return config dict."
    with ConfigZK(**kwargs) as zk:
        return zk[path]


def from_file(file: pathlib.Path) -> dict[Any, Any]:
    "Read file (yaml or json), return dict."
    file = pathlib.Path(file)
    with file.open("r") as f:
        if file.suffix in (".yaml", ".yml"):
            return yaml.load(f, Loader=yaml.loader.Loader) or dict()
        elif file.suffix == ".json":
            return json.load(f) or dict()
    raise ValueError(f"Config at {file} should be a .yaml or .json file.")


def normalize_zk_path(path: str) -> str:
    """
    >>> normalize_zk_path("project/config")
    '/project/config'
    >>> normalize_zk_path("\\\\project\\config")
    '/project/config'
    """
    path = str(path).replace("\\", "/")
    while path[0] != "/" or path[1] == "/":
        path = "/" + path.lstrip("/")
    return path


def fetch(arg: str | Mapping | pathlib.Path, **kwargs) -> dict[Any, Any]:
    "Differentiate a file path from a ZK path and return corresponding dict."

    if isinstance(arg, Mapping):
        config = arg

    elif isinstance(arg, (str, pathlib.Path)):
        # first rule-out that the output isn't a filepath
        path = pathlib.Path(str(arg)).resolve()
        if path.is_file() or path.suffix:
            config = from_file(path)

        elif isinstance(arg, str):
            # likely a ZK path
            path_str = normalize_zk_path(arg)
            config = from_zk(path_str, **kwargs)
    else:
        raise ValueError(
            "Logging config input should be a path to a .yaml or .json file, a ZooKeeper path, or a python logging config dict."
        )

    return dict(**config)


def to_file(config: dict, file: pathlib.Path):
    "Dump dict to file (yaml or json, based on file extension supplied)."
    file = pathlib.Path(file)
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("w") as f:
        if file.suffix == ".yaml":
            return yaml.dump(config, f)
        elif file.suffix == ".json":
            return json.dump(config, f, indent=4, default=str)
    raise ValueError(f"Logging config {file} should be a .yaml or .json file.")


def to_zk(config: dict, path: str):
    "Dump config to Zookeeper at path, deleting path if config is empty."
    path = normalize_zk_path(path)
    with ConfigZK() as zk:
        if not config:
            del zk[path]
        else:
            zk[path] = config


def host_responsive(host: str) -> bool:
    """
    Remember that a host may not respond to a ping (ICMP) request even if the host name
    is valid. https://stackoverflow.com/a/32684938
    """
    param = "-n" if platform.system().lower() == "windows" else "-c"
    command = ["ping", param, "1", host]
    return subprocess.call(command, stdout=subprocess.PIPE) == 0


def backup_zk(file: pathlib.Path = LOCAL_ZK_BACKUP_FILE):
    "Recursively backup all zookeeper records to local file."
    zk = ConfigZK()
    backup = dict()

    def get(zk: ConfigZK, parent="/"):
        children = zk.get_children(parent)
        if not children:
            return
        for child in children:
            key = parent + child if parent == "/" else "/".join([parent, child])
            try:
                value = zk[key]
            except KeyError:
                continue
            if value:
                backup[key] = value
            else:
                get(zk, key)

    with zk:
        get(zk)
    to_file(backup, file)


class ConfigFile(collections.UserDict):
    """
    A dictionary wrapper around a continuously-synced serialized local copy of a config.

    Used for keeping a full backup of all configs on zookeeper, or for keeping a record
    of the config fetched during a session.
    """

    lock: threading.Lock = threading.Lock()
    read_only: bool = False

    def __init__(self, file: pathlib.Path = SESSION_ZK_RECORD_FILE, dict=None):
        self.file = pathlib.Path(file)
        if not dict and self.file.exists():
            dict = from_file(self.file)
        super().__init__(dict)

    def write(self):
        if self.read_only:
            logger.debug("Not writing to read-only config file %s", self.file)
            return
        if not self.file.exists():
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.touch(exist_ok=True)
        with self.lock, contextlib.suppress(Exception):
            to_file(self.data, self.file)
            logger.debug(f"Updated local config file {self.file}")
            return
        logger.debug(
            f"Could not update local config file {self.file}", exc_info=True,
        )

    def __getitem__(self, key: Any):
        logger.debug(f"Fetching {key!r} from local config backup")
        try:
            value = super().__getitem__(key)
        except Exception as exc:
            raise KeyError(
                f"{key!r} not found in local config file {self.file}"
            ) from exc
        return value

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.write()
        logger.debug(f"{key!r} updated in local config file {self.file}")

    def __delitem__(self, key: Any):
        try:
            super().__delitem__(key)
        except Exception as exc:
            raise KeyError(
                f"{key!r} not found in local config file {self.file}"
            ) from exc
        else:
            self.write()
            logger.debug(f"{key!r} deleted from local config file {self.file}")

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        self.write()


class ConfigZK(KazooClient):
    def __init__(self, hosts: str = ZK_HOST_PORT, *args, **kwargs):
        """
        A dictionary and context-manager wrapper around the zookeeper interface - modified from
        mpeconfig ConfigServer.
        """
        super().__init__(hosts, timeout=10)

    @contextlib.contextmanager
    def _start(self) -> Generator["ConfigZK", None, None]:
        "Start the client via contextmanager if not already started."
        # contextlib.nullcontext preferred in 3.7+
        if not self.connected:
            with self:
                yield self
            self.__exit__()
        else:
            yield self

    def get(self, key: Any, default: Any = None) -> Any:
        "Overload KazooClient.get())"
        try:
            return self[key]
        except KeyError:
            return default

    def __getitem__(self, key) -> dict:
        with self._start():
            try:
                node = super().get(key)
            except Exception as exc:
                raise KeyError(f"{key!r} not found in zookeeper.") from exc
            else:
                item = node[0] if node and len(node) else None
                value = yaml.load(item or "", Loader=yaml.loader.Loader) or dict()
                return value

    def __setitem__(self, key, value):
        with self._start():
            self.ensure_path(key)
            super().set(key, bytes(yaml.dump(value or dict()), "utf-8"))

    def __delitem__(self, key):
        with self._start():
            try:
                super().delete(key)
            except Exception as exc:
                raise KeyError(f"{key!r} not found in zookeeper.") from exc

    def __enter__(self):
        if self.connected:
            return self
        try:
            self.start(timeout=10)
        except Exception as exc:
            if not is_connected():
                logger.debug(
                    "Starting the Kazoo client failed: %s", self.hosts, exc_info=True
                )
                raise ConnectionError(
                    f"Zookeeper server is unreachable: {MINDSCOPE_SERVER}"
                ) from exc
            raise exc
        else:
            return self

    def __exit__(self, *args, **kwargs):
        self.stop()


class RecordedZK(ConfigZK):

    skip_record = False
    record: ConfigFile
    "Dict class that records accessed keys on file."

    def __init__(self, record_file=SESSION_ZK_RECORD_FILE, *args, **kwargs):
        """
        A ZK config dict wrapper that records all keys accessed during a session to file.
        """
        self.record = ConfigFile(record_file)
        with self.no_record():
            super().__init__(*args, **kwargs)

    def __getitem__(self, key):
        value = super().__getitem__(key)
        if not self.skip_record:
            self.record[key] = value
        return value

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if not self.skip_record:
            self.record[key] = value

    @contextlib.contextmanager
    def no_record(self) -> Generator[None, None, None]:
        logger.debug("Temporarily pausing record keeping %s.", self.__class__)
        self.skip_record = True
        try:
            yield
        finally:
            self.skip_record = False
            logger.debug("Resuming record keeping %s.", self.__class__)


SESSION_ZK_RECORD: RecordedZK = recorded_zk_config()


class BackedUpZK(ConfigZK, ConfigFile):
    def __init__(
        self, backup_file: pathlib.Path = LOCAL_ZK_BACKUP_FILE, *args, **kwargs
    ):
        """
        Zookeeper wrapper that pulls from local backup if server is not responsive.
        """
        test = ConfigZK(*args, **kwargs)
        try:
            _ = test.get_children("/")
        except:
            logger.debug("Could not connect to Zookeeper, using local backup file.")
            self.__class__ = ConfigFile
            ConfigFile.__init__(self, file=backup_file, *args, **kwargs)
            self.read_only = True

        self.__class__ = ConfigZK
        ConfigZK.__init__(self, *args, **kwargs)


# class Backedup(ConfigZK):

#     config: ConfigZK()
#     backup: ConfigFile

#     def __init__(self, backup_file: pathlib.Path = LOCAL_ZK_BACKUP_FILE, *args, **kwargs):
#         """
#         Zookeeper wrapper that pulls from local backup if server is not responsive.
#         """
#         self.backup = ConfigFile(backup_file)
#         with self.backup():
#             self.config.__init__(*args, **kwargs)

#     @contextlib.contextmanager
#     def backup(self) -> Generator[None, None, None]:
#         if not host_responsive(MINDSCOPE_SERVER):
#             logger.debug("Could not connect to Zookeeper, using local backup file.")
#             self.config = __class__.backup
#         yield
#         self.config = __class__.config

#     def __enter__(self):
#         with self.backup():
#             return self.config.__enter__()

#     def __exit__(self, *args, **kwargs):
#         with self.backup():
#             return self.config.__exit__(*args, **kwargs)

#     def __getitem__(self, key: Any):
#         with self.backup():
#             return self.config.__getitem__(key)

#     def __setitem__(self, key, value):
#         with self.backup():
#             self.config.__setitem__(key, value)

# ZK_BACKUP = ConfigFile(LOCAL_ZK_BACKUP_FILE)

if __name__ == "__main__":
    import doctest

    doctest.testmod()
