"""Access to rig computer hostnames and rig-wide ZooKeeper configs.

::
### When running on a rig-attached computer

AIBS MPE computer and rig IDs:
>>> COMP_ID, RIG_ID, RIG_IDX        # doctest: +SKIP
'NP.1-Acq', 'NP.1', 1


### For specific rigs

AIBS MPE rig ID:
>>> Rig(1).id
'NP.1'

Hostnames for each rig computer [Sync, Mon, Acq, Stim]:
>>> Rig(1).Acq
'W10DT713843'

Paths for specific apps running on a rig:
>>> Rig(1).paths['MVR']
WindowsPath('//W10DTSM18278/c$/ProgramData/AIBS_MPE/mvr/data')

Config dict for a particular rig, fetched from ZooKeeper /rigs/NP.<idx>:
>>> Rig(1).config['Acq']
'W10DT713843'

When running on a rig, its NP-index is obtained from an env var, making the current rig's
properties available by default:
>>> Rig().Acq                       # doctest: +SKIP 
'W10DT713843'

>>> Rig().config['Acq']             # doctest: +SKIP
'W10DT713843'

If app is running on the local computer, its path is represented as a local path:
>>> Rig().paths['Sync']             # doctest: +SKIP
WindowsPath('C:/ProgramData/AIBS_MPE/sync/data')

...otherwise, as a network path:
>>> Rig().paths['Stim']             # doctest: +SKIP
WindowsPath('//W10DT713942/c$/ProgramData/AIBS_MPE/camstim/data')

"""
from __future__ import annotations

import contextlib
import doctest
import functools
import logging
import os
import pathlib
import re
from typing import Any, Hashable, Optional

import requests

if __name__ == "__main__":
    import utils

    import np_config
else:
    from . import np_config, utils

logger = logging.getLogger(__name__)

# all mpe computers --------------------------------------------------------------------

SERVER = "http://mpe-computers/v2.0"

comp_ids, rig_ids, cluster_ids = requests.get(SERVER).json().values()

# make mappings for easier lookup
RIG_ID_TO_COMP_IDS: dict[str, list[str]] = {
    k: v.get("comp_ids", []) for k, v in rig_ids.items()
}
"Keys are rig IDs (`NP.1`), values are lists of computer IDs (`['NP.1-Acq', ...]`)."

COMP_ID_TO_HOSTNAME: dict[str, str] = {
    k: v.get("hostname", "").upper() for k, v in comp_ids.items()
}
"Keys are computer IDs (`NP.1-Acq`), values are hostnames (`W10DT713843`)."

HOSTNAME_TO_COMP_ID: dict[str, str] = {
    v.upper(): k for k, v in COMP_ID_TO_HOSTNAME.items()
}
"Keys are hostnames (`W10DT713843`), values are computer IDs (`NP.1-Acq`)."

RIG_ID_TO_HOSTNAMES: dict[str, list[str]] = {
    k: [COMP_ID_TO_HOSTNAME[comp_id] for comp_id in v]
    for k, v in RIG_ID_TO_COMP_IDS.items()
}
"Keys are rig IDs (`NP.1`), values are lists of hostnames (`['W10DT713843', ...]`)."

# local computer properties ------------------------------------------------------------

HOSTNAME = utils.HOSTNAME

COMP_ID: str | None = (
    HOSTNAME_TO_COMP_ID.get(HOSTNAME) or os.environ.get("AIBS_COMP_ID") or None
)
"AIBS MPE comp ID for this computer, e.g. `NP.1-Sync`."

RIG_ID: str | None = (
    os.environ.get("AIBS_RIG_ID", "").upper()
    or comp_ids.get(COMP_ID, {}).get("rig_id")
    or (f"NP.{utils.rig_idx(COMP_ID)}"
        if COMP_ID and utils.rig_idx(COMP_ID) is not None
        else None
    )
    or ("BTVTest.1" if os.environ.get("USE_TEST_RIG", False) else None)
    or None
)
"AIBS MPE NP-rig ID, e.g. `'NP.1'` if running on a computer connected to NP.1."

RIG_IDX: int | None = utils.rig_idx(RIG_ID)
"AIBS MPE NP-rig index, e.g. `1` if running on a computer connected to NP.1."

if not RIG_ID:
    logger.debug(
        "Not running from an NP rig: connections to services won't be made. To use BTVTest.1, set env var `USE_TEST_RIG = 1`"
    )

logger.info(
    f"Running from {COMP_ID or HOSTNAME}, {'connected to ' + RIG_ID if RIG_ID else 'not connected to a rig'}"
)


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
    >>> Rig(1).config['Acq']
    'W10DT713843'

    When running on a rig, its NP-index is obtained from an env var, making the current rig's
    properties available by default (equivalent to `Rig(RIG_IDX)`):
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
        idx_or_name = RIG_IDX if idx_or_id is None else idx_or_id
        if idx_or_name is None:
            raise ValueError("Rig index not specified and not running on a rig.")
        idx = utils.rig_idx(idx_or_name)
        if idx is None:
            raise ValueError(f"`NP.{idx}` is not a recognized NP-rig") 
        self.idx: int = idx
        self.id: str = f"NP.{idx}"
        for comp in ('sync', 'stim', 'mon', 'acq'):
            setattr(self, f'_{comp}', COMP_ID_TO_HOSTNAME[f'{self.id}-{comp.title()}'])

    def __str__(self) -> str:
        return self.id
    
    def __repr__(self):
        return f'{__class__.__name__}({self.id!r})'
    
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

    @functools.cached_property
    def config(self) -> dict[Hashable, Any]:
        "Rig-specific config dict, fetched from ZooKeeper."
        return utils.merge(
            np_config.from_zk("/np_defaults/configuration"),
            np_config.from_zk(f"/rigs/{self.id}"),
        )

    @functools.cached_property
    def paths(self) -> dict[str, pathlib.Path]:
        """Network paths to data folders for various devices/services, using 
        values from ZooKeeper /np_defaults/configuration and /rigs/NP.<idx>/paths.
        """       
        paths = dict()
        
        for service, service_config in self.config['services'].items():
            if 'data' not in service_config:
                continue
            data = service_config['data']
            host = getattr(self, service, service_config.get('host', None))
            if not host:
                continue
            if host in RIG_ID_TO_HOSTNAMES[self.id]:
                paths[str(service)] = utils.local_or_unc_path(host=host, path=service_config['data'])
            else:
                paths[str(service)] = utils.normalize_path(f'//{host}/{data}')
        for name, path in self.config.get('paths', {}).items():
           paths[str(name)] = utils.normalize_path(path)
        
        return paths
    
RIG_CONFIG: dict[Hashable, Any] | None = Rig().config if RIG_IDX else None
"Rig-specific config dict, fetched from ZooKeeper, or `None` if not running on a rig."

if __name__ == "__main__":
    doctest.testmod()
