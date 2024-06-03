"""Access to rig computer hostnames and rig-wide ZooKeeper configs.

::
### When running on a rig-attached computer

AIBS MPE computer and rig IDs:
>>> COMP_ID, get_rig_id(), get_rig_idx()        # doctest: +SKIP
'NP.1-Acq', 'NP.1', 1


### For specific rigs

AIBS MPE rig ID:
>>> Rig(1).id
'NP.1'

Hostnames for each rig computer [Sync, Mon, Acq, Stim]:
>>> Rig(1).Acq
'W10DT713843'

Paths for specific apps running on a rig:
>>> Rig(1).paths['MVR'].as_posix()
'//W10DTSM118295/c$/ProgramData/AIBS_MPE/mvr/data'

Config dict for a particular rig, fetched from ZooKeeper /rigs/NP.<idx>:
>>> Rig(1).config['pretest_mouse']        
599657

When running on a rig, its NP-index is obtained from an env var, making the current rig's
properties available by default:
>>> Rig().Acq                       # doctest: +SKIP 
'W10DT713843'

If app is running on the local computer, its path is represented as a local path:
>>> Rig().paths['Sync']             # doctest: +SKIP
WindowsPath('C:/ProgramData/AIBS_MPE/sync/data')

...otherwise, as a network path:
>>> Rig().paths['Stim']             # doctest: +SKIP
WindowsPath('//W10DT713942/c$/ProgramData/AIBS_MPE/camstim/data')

"""
from __future__ import annotations

import doctest
import functools
import logging
import os
import pathlib
from typing import Any, Hashable, Optional

import requests
from backports.cached_property import cached_property
from typing_extensions import Literal

import np_config.config as config
import np_config.utils as utils

logger = logging.getLogger(__name__)

# all mpe computers --------------------------------------------------------------------

SERVER = "http://mpe-computers/v2.0"


@functools.cache
def get_mpe_computer_ids(key: Literal['comp_ids', 'rig_ids', 'cluster_ids'] | None = None) -> dict[str, Any]:
    """Get a mapping of computer/rig/cluster IDs and their corresponding information."""
    all_ids = requests.get(SERVER).json()
    if key:
        return all_ids[key]
    return all_ids

get_comp_ids = functools.partial(get_mpe_computer_ids, "comp_ids")
get_rig_ids = functools.partial(get_mpe_computer_ids, "rig_ids")
get_cluster_ids = functools.partial(get_mpe_computer_ids, "cluster_ids")

# make mappings for easier lookup
def get_id_to_comp_ids() -> dict[str, list[str]]:
    "Keys are rig IDs (`NP.1`), values are lists of computer IDs (`['NP.1-Acq', ...]`)."
    return {k: v.get("comp_ids", []) for k, v in get_rig_ids().items()}

def get_comp_id_to_hostname() -> dict[str, str]:
    "Keys are computer IDs (`NP.1-Acq`), values are hostnames (`W10DT713843`)."
    return {k: v.get("hostname", "").upper() for k, v in get_comp_ids().items()}

def get_hostname_to_comp_id() -> dict[str, str]:
    "Keys are hostnames (`W10DT713843`), values are computer IDs (`NP.1-Acq`)."
    return {v.upper(): k for k, v in get_comp_id_to_hostname().items()}

def get_rig_id_to_hostnames() -> dict[str, list[str]]:
    "Keys are rig IDs (`NP.1`), values are lists of hostnames (`['W10DT713843', ...]`)."
    return {k: [get_comp_id_to_hostname()[comp_id] for comp_id in v] for k, v in get_id_to_comp_ids().items()}

# local computer properties ------------------------------------------------------------

@functools.cache
def get_comp_id() -> str | None:
    "AIBS MPE comp ID for this computer, e.g. `NP.1-Sync`."
    return get_hostname_to_comp_id().get(utils.HOSTNAME) or os.environ.get("AIBS_COMP_ID") or None

@functools.cache
def get_rig_id() -> str | None:
    "AIBS MPE NP-rig ID, e.g. `'NP.1'` if running on a computer connected to NP.1."
    return (
        os.environ.get("AIBS_RIG_ID", "").upper()
        or get_comp_ids().get(get_comp_id(), {}).get("rig_id")
        or (
            f"NP.{utils.rig_idx(get_comp_id())}"
            if get_comp_id() and utils.rig_idx(get_comp_id()) is not None
            else None
        )
        or ("BTVTest.1" if os.environ.get("USE_TEST_RIG", False) else None)
        or None
    )

def get_rig_idx() -> int | None:
    "AIBS MPE NP-rig index, e.g. `1` if running on a computer connected to NP.1."
    return utils.rig_idx(get_rig_id())

class Rig:
    """Access to rig computer hostnames and rig-wide ZooKeeper configs.
    ::
    
    AIBS MPE rig ID:
    >>> Rig(1).id
    'NP.1'

    Hostnames for each rig computer [Sync, Mon, Acq, Stim]:
    >>> Rig(1).Acq
    'W10DT713843'

    Config dict for a particular rig, fetched from ZooKeeper /rigs/NP.<idx>:
    >>> Rig(1).config['pretest_mouse']
    599657

    When running on a rig, its NP-index is obtained from an env var, making the current rig's
    properties available by default (equivalent to `Rig(get_rig_idx())`):
    >>> Rig().Acq                       # doctest: +SKIP 
    'W10DT713843'

    >>> Rig().config['Acq']             # doctest: +SKIP
    'W10DT713843'

    """

    id: str
    "AIBS MPE rig ID, e.g. `NP.1`"
    idx: int
    "AIBS MPE NP-rig index, e.g. `1` for NP.1"

    _sync: str
    _stim: str
    _mon: str
    _acq: str

    def __init__(self, idx_or_id: Optional[int | str] = None):
        idx_or_name = get_rig_idx() if idx_or_id is None else idx_or_id
        if idx_or_name is None:
            raise ValueError("Rig index not specified and not running on a rig.")
        idx = utils.rig_idx(str(idx_or_name))
        if idx is None:
            raise ValueError(f"`NP.{idx}` is not a recognized NP-rig")
        self.idx: int = idx
        self.id: str = f"NP.{idx}"
        for comp in ("sync", "stim", "mon", "acq"):
            setattr(self, f"_{comp}", get_comp_id_to_hostname()[f"{self.id}-{comp.title()}"])

    def __str__(self) -> str:
        return self.id

    def __repr__(self):
        return f"{self.__class__.__name__}({self.id!r})"

    @property
    def sync(self) -> str:
        "Hostname for the Sync computer."
        return self._sync

    SYNC = Sync = sync

    @property
    def mon(self) -> str:
        "Hostname for the Mon computer."
        return self._mon

    MON = Mon = vidmon = VidMon = VIDMON = mon

    @property
    def acq(self) -> str:
        "Hostname for the Acq computer."
        return self._acq

    ACQ = Acq = acq

    @property
    def stim(self) -> str:
        "Hostname for the Stim computer."
        return self._stim

    STIM = Stim = stim

    @cached_property
    def config(self) -> dict[Hashable, Any]:
        "Rig-specific config dict, fetched from ZooKeeper."
        return utils.merge(
            config.from_zk("/np_defaults/configuration"),
            config.from_zk(f"/rigs/{self.id}"),
        )

    @property
    def paths(self) -> dict[str, pathlib.Path]:
        """Network paths to data folders for various devices/services, using 
        values from ZooKeeper /np_defaults/configuration and
        /rigs/NP.<idx>/paths.
        
        >>> Rig(1).paths['Sync'].as_posix()
        '//W10DT26AD0025/c$/ProgramData/AIBS_MPE/sync/data'
        """
        paths = dict()

        for service, service_config in self.config["services"].items():
            if "data" not in service_config:
                continue
            data_path = service_config["data"]
            host = getattr(self, service_config.get("comp"), None) or service_config["host"]
            if host in get_rig_id_to_hostnames()[self.id]:
                paths[str(service)] = utils.local_or_unc_path(
                    host=host, path=service_config["data"]
                )
            else:
                paths[str(service)] = utils.normalize_path(f"//{host}/{data_path}")
        for name, path in self.config.get("paths", {}).items():
            paths[str(name)] = utils.normalize_path(path)

        return paths

    @property
    def mvr_config(self) -> pathlib.Path:
        "Path to MVR config file for this rig."
        return utils.normalize_path(
            f"//{self.mon}/c$/ProgramData/AIBS_MPE/mvr/config/mvr.ini"
        )
    
    @property
    def sync_config(self) -> pathlib.Path:
        "Path to sync config file for this rig."
        return utils.normalize_path(
            f'//{self.sync}/c$/ProgramData/AIBS_MPE/sync/config/sync.yml'
        )

    @property
    def camstim_config(self) -> pathlib.Path:
        "Path to camstim config file for this rig."
        return utils.normalize_path(
            f'//{self.stim}/c$/ProgramData/AIBS_MPE/camstim/config/camstim.yml'
        )

def get_rig_config(idx_or_id: Optional[int | str] = None) -> dict[Hashable, Any] | None:
    """Get the rig-specific config dict for the specified rig index or ID, fetched
    from ZooKeeper. If no index or ID is provided, returns the config dict for the
    current rig, if running on an NP rig.
    
    >>> get_rig_config(1)['pretest_mouse']
    599657
    """
    if idx_or_id is None:
        return Rig().config if get_rig_idx() else None
    return Rig(idx_or_id).config


if __name__ == "__main__":
    doctest.testmod()
