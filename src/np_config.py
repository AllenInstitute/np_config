from __future__ import annotations

import collections
import json
import logging
import pathlib
import platform
import subprocess
import threading
from typing import Any, Dict, Mapping, Union

import yaml
from kazoo.client import KazooClient

ROOT_DIR = pathlib.Path(__file__).absolute().parent.parent
DEFAULT_ZK_BACKUP_PATH = ROOT_DIR / "resources" / "zk_backup.json"

# preserve order of keys in dict 
yaml.add_representer(
    dict,
    lambda self, data: yaml.representer.SafeRepresenter.represent_dict(
        self, data.items()
    ),
)

def fetch_zk_config(path: str) -> Dict:
    "Access eng-mindscope Zookeeper, return config dict."
    with ConfigServer() as zk:
        return zk[path]

def fetch_file_config(path: pathlib.Path) -> Dict:
    "Read file (yaml or json), return dict."
    try:
        with path.open() as f:
            if path.suffix == ".yaml":
                return yaml.load(f, Loader=yaml.loader.Loader)
            if path.suffix == ".json":
                return json.load(f)
        raise ValueError(f"Logging config {path} should be a .yaml or .json file.")
    except:
        return dict()

def fetch_config(arg: Union[str, Mapping, pathlib.Path]) -> Dict[Any, Any]:
    "Differentiate a file path from a ZK path and return corresponding dict."

    if isinstance(arg, Mapping):
        config = arg

    elif isinstance(arg, (str, pathlib.Path)):
        # first rule-out that the output isn't a filepath
        path = pathlib.Path(arg).resolve()
        if path.is_file() or path.suffix:
            config = fetch_file_config(path)

        elif isinstance(arg, str):
            # likely a ZK path
            path = arg.replace("\\", "/")
            if path[0] != "/":
                path = "/" + path
            config = fetch_zk_config(path)
    else:
        raise ValueError(
            "Logging config input should be a path to a .yaml or .json file, a ZooKeeper path, or a python logging config dict."
        )

    return dict(**config)

def dump_file_config(config: Dict, path: pathlib.Path):
    "Dump dict to file (yaml or json)"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as f:
        if path.suffix == ".yaml":
            return yaml.dump(config, f)
        elif path.suffix == ".json":
            return json.dump(config, f, indent=4)
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
    A dictionary wrapper around a serialized local copy of previously fetched zookeeper records.
    """
    
    file: pathlib.Path = DEFAULT_ZK_BACKUP_PATH
    lock: threading.Lock = threading.Lock()

    def __init__(self):
        if not self.file.exists():
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.touch()
        super().__init__()
        self.data = fetch_file_config(self.file)
    
    def write(self):    
        with self.lock:
            try:
                dump_file_config(self.data, self.file)
                logging.debug(f"Updated local zookeeper backup file {self.file}")
            except OSError:
                pass
            
    def __getitem__(self, key: Any):
        logging.debug(f"Fetching {key} from local zookeeper backup")
        return super().__getitem__(key)
    
    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        logging.debug(f"{key} updated in local zookeeper backup")
        self.write()
        
    def __delitem__(self, key: Any):
        if key in self.data.keys():
            super().__delitem__(key)
            logging.debug(f"{key} deleted from local zookeeper backup")
            self.write()
        
    def __enter__(self):
        return self
    
    def __exit__(self, exception_type, exception_value, traceback):
        self.write()   
     
     
class ConfigServer(KazooClient):
    """
    A dictionary and context API wrapper around the zookeeper interface, with local json
    backup - modified from mpeconfig.
    """
    backup = ConfigFile()
    
    def __new__(cls, *args, **kwargs) -> Union[KazooClient, ConfigFile]:
        if not host_responsive("eng-mindscope.corp.alleninstitute.org"):
            logging.debug('Could not connect to Zookeeper, using local backup file.')
            return cls.backup
        return super().__new__(cls)
    
    def __init__(self, hosts="eng-mindscope:2181"):
        super().__init__(hosts, timeout=10)
        with self as zk:
            zk.backup_all()

    def backup_all(self, path="/"):
        "Recursively backup all zookeeper records to local json file."
        for key in self.get_children(path):
            path = "/".join([path, key]) if path != "/" else "/" + key
            try:
                value = self.get(path)[0]
            except:
                continue
            if value:
                self.backup[f"{path}"] = yaml.load(self.get(path)[0], Loader=yaml.loader.Loader)
            else:
                self.backup_all(path)
    
    def __getitem__(self, key) -> Dict:
        if self.exists(key):
            value = yaml.load(self.get(key)[0], Loader=yaml.loader.Loader)
            self.backup[key] = value
            return value
        else:
            raise KeyError(key)

    def __setitem__(self, key, value):
        self.ensure_path(key)
        self.set(key, value)
        self.backup[key] = value
        
    def __delitem__(self, key):
        if self.exists(key):
            self.delete(key)
            del self.backup[key]
            
    def __enter__(self):
        try:
            self.start(timeout=1)
        except Exception as exc:
            if not self.connected:
                logging.warning(f"Could not connect to zookeeper server {self.hosts}")
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        self.stop()
   