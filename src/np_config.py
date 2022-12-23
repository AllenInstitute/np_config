import collections
import datetime
import json
import logging
import pathlib
import platform
import subprocess
import threading
from typing import Any, Dict, Mapping, Union

import yaml
from kazoo.client import KazooClient

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
LOCAL_DATA_PATH = ROOT_DIR / "resources"

LOCAL_ZK_BACKUP_PATH = LOCAL_DATA_PATH / "zk_backup.yaml"
"File for keeping a full backup of Zookeeper configs."

session_start_time = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
CURRENT_SESSION_ZK_RECORD_PATH = LOCAL_DATA_PATH / f"zk_record-{pathlib.Path().cwd().name}-{session_start_time}.yaml"
"File for keeping a record of configs accessed from ZK during the current session."

SESSION_RECORD: collections.UserDict

def from_zk(path: str) -> Dict:
    "Access eng-mindscope Zookeeper, return config dict."
    with ConfigServer() as zk:
        return zk[path]


def from_file(path: pathlib.Path) -> Dict:
    "Read file (yaml or json), return dict."
    with path.open('r') as f:
        if path.suffix in (".yaml", ".yml"):
            return yaml.load(f, Loader=yaml.loader.Loader) or dict()
        elif path.suffix == ".json":
            return json.load(f, path) or dict()
    raise ValueError(f"Config at {path} should be a .yaml or .json file.")
    

def fetch(arg: Union[str, Mapping, pathlib.Path]) -> Dict[Any, Any]:
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
            path_str = arg.replace("\\", "/")
            if path_str[0] != "/":
                path_str = "/" + path_str
            config = from_zk(path_str)
    else:
        raise ValueError(
            "Logging config input should be a path to a .yaml or .json file, a ZooKeeper path, or a python logging config dict."
        )

    return dict(**config)


def dump_file(config: Dict, path: pathlib.Path):
    "Dump dict to file (yaml or json)"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        if path.suffix == ".yaml":
            return yaml.dump(config, f)
        elif path.suffix == ".json":
            return json.dump(config, f, indent=4, default=str)

    raise ValueError(f"Logging config {path} should be a .yaml or .json file.")


def host_responsive(host: str) -> bool:
    """
    Remember that a host may not respond to a ping (ICMP) request even if the host name
    is valid. https://stackoverflow.com/a/32684938
    """
    param = "-n" if platform.system().lower() == "windows" else "-c"
    command = ["ping", param, "1", host]
    return subprocess.call(command, stdout=subprocess.PIPE) == 0


class ConfigFile(collections.UserDict):
    """
    A dictionary wrapper around a serialized local copy of a config.
    
    Used for keeping a full backup of all configs on zookeeper, or for keeping a record
    of the config fetched during a session.
    """

    lock: threading.Lock = threading.Lock()

    def __init__(self, file: pathlib.Path = CURRENT_SESSION_ZK_RECORD_PATH):
        super().__init__()
        self.file = file
        if self.file.exists():
            self.data = from_file(self.file)

    def write(self):
        if not self.file.exists():
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.touch(exist_ok=True)
        with self.lock:
            try:
                dump_file(self.data, self.file)
            except OSError:
                logging.debug(
                    f"Could not update local config file {self.file}",
                    exc_info=True,
                )
                pass
            else:
                logging.debug(f"Updated local config file {self.file}")

    def __getitem__(self, key: Any):
        logging.debug(f"Fetching {key} from local config backup")
        try:
            super().__getitem__(key)
        except Exception as exc:
            raise KeyError(
                f"{key} not found in local config file {self.file}"
            ) from exc

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.write()
        logging.debug(f"{key} updated in local config file")

    def __delitem__(self, key: Any):
        try:
            super().__delitem__(key)
        except Exception as exc:
            raise KeyError(
                f"{key} not found in local config file {self.file}"
            ) from exc
        else:
            self.write()
            logging.debug(f"{key} deleted from local config file")

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        self.write()

SESSION_RECORD: collections.UserDict = ConfigFile(CURRENT_SESSION_ZK_RECORD_PATH)
    
class ConfigServer(KazooClient):
    """
    A dictionary and context API wrapper around the zookeeper interface, with local json
    backup - modified from mpeconfig.
    """

    backup = ConfigFile(LOCAL_ZK_BACKUP_PATH)
    "Keeps a local backup of all zookeeper records."
    record: ConfigFile = SESSION_RECORD
    "Keeps a log of all zookeeper records fetched during a session."
    
    def __new__(cls, *args, **kwargs) -> Union[KazooClient, ConfigFile]:  # type: ignore
        if not host_responsive(MINDSCOPE_SERVER):
            logging.debug("Could not connect to Zookeeper, using local backup file.")
            return cls.backup
        return super().__new__(cls)

    def __init__(self, hosts: str = ZK_HOST_PORT, disable_record_keeping: bool = False):
        super().__init__(hosts, timeout=10)
        self.disable_record_keeping = disable_record_keeping
    
    def update_session_record(self, key: str, value: Dict):
        if not self.disable_record_keeping:
            self.record[key] = value
    
    def __getitem__(self, key) -> Dict:
        try:
            node = self.get(key)
        except:
            raise KeyError(f"{key} not found in zookeeper.")
        else:
            value = yaml.load(node[0] or '', Loader=yaml.loader.Loader) or dict()
            self.update_session_record(key, value)
            return value

    def __setitem__(self, key, value):
        self.ensure_path(key)
        self.set(key, bytes(yaml.dump(value or dict()), 'utf-8'))
        self.update_session_record(key, value)

    def __delitem__(self, key):
        try:
            self.delete(key)
        except Exception as exc:
            raise KeyError(f"{key} not found in zookeeper.") from exc
        
    def __enter__(self):
        try:
            self.start(timeout=1)
        except:
            if not self.connected:
                logging.warning(f"Could not connect to zookeeper server {self.hosts}", exc_info=True)
                return self.backup
        else:
            return self
        raise 

    def __exit__(self, exception_type, exception_value, traceback):
        self.stop()


def backup_zk(zk: ConfigServer = None):
    "Recursively backup all zookeeper records to local file."
    if not zk:
        zk = ConfigServer(disable_record_keeping=True)
        
    if isinstance(zk, ConfigServer.backup.__class__): 
        logging.debug("Could not connect to zookeeper, skipping backup.")
        return
    
    def backup(zk: ConfigServer, parent="/"):
        for key in zk.get_children(parent):
            path = "/".join([parent, key]) if parent != "/" else "/" + key
            try:
                value = zk[path]
            except KeyError:
                continue
            if value:
                zk.backup[path] = value
            else:
                backup(zk, path)
    with zk:
        backup(zk)

backup_zk() 
# we need to know that zk and the file backup are accesible at startup, this is a good
# test of both and a regular full backup is desirable anyway