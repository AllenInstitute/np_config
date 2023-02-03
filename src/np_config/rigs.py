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

Config dict for a particular rig, fetched from ZooKeeper /rigs/NP.<idx>:
>>> Rig(1).config['Acq']
'W10DT713843'

When running on a rig, its NP-index is obtained from an env var, making the current rig's
properties available by default:
>>> Rig().Acq                       # doctest: +SKIP 
'W10DT713843'

>>> Rig().config['Acq']             # doctest: +SKIP
'W10DT713843'

"""
from __future__ import annotations

import logging
import os
import re
import socket
from enum import Enum
from typing import Any, Optional

import requests

import np_config

logger = logging.getLogger(__name__)

# all mpe computers --------------------------------------------------------------------

SERVER = "http://mpe-computers/v2.0"

comp_ids, rig_ids, cluster_ids = requests.get(SERVER).json().values()

# make mappings for easier lookup
RIG_ID_TO_COMP_IDS: dict[str, list[str]] =  {k: v.get('comp_ids', []) for k,v in rig_ids.items()}
"Keys are rig IDs (`NP.1`), values are lists of computer IDs (`['NP.1-Acq', ...]`)."

COMP_ID_TO_HOSTNAME: dict[str, str] = {k: v.get('hostname', '').upper() for k,v in comp_ids.items()}
"Keys are computer IDs (`NP.1-Acq`), values are hostnames (`W10DT713843`)."

HOSTNAME_TO_COMP_ID: dict[str, str] = {v.upper(): k for k,v in COMP_ID_TO_HOSTNAME.items()}
"Keys are hostnames (`W10DT713843`), values are computer IDs (`NP.1-Acq`)."


# local computer properties ------------------------------------------------------------

HOSTNAME = socket.gethostname().upper()

COMP_ID: str = (
    HOSTNAME_TO_COMP_ID.get(HOSTNAME)
    or os.environ.get("AIBS_COMP_ID")
    or HOSTNAME
)
"AIBS MPE computer ID for this computer, e.g. `NP.1-Sync`, or hostname if not a rig-connected computer."

RIG_ID: str | None = (
    os.environ.get("AIBS_RIG_ID", "").upper()
    or comp_ids.get(COMP_ID, {}).get("rig_id")
    or (re.findall(R"NP.[\d]+", COMP_ID)[0] if re.findall(R"NP.[\d]+", COMP_ID) else None)
    or ("BTVTest.1" if os.environ.get("USE_TEST_RIG", False) else None)
    or None
)
"AIBS MPE rig ID, e.g. `NP.1`, if running on a rig-connected computer."

RIG_IDX: int | None = re.findall(R"NP.([\d]+)", RIG_ID)[0] if RIG_ID and "NP." in RIG_ID else None
"AIBS MPE NP-rig index, e.g. `1` for NP.1, if running on a rig-connected computer."

if not RIG_ID:
    logger.debug("Not running from an NP rig: connections to services won't be made. To use BTVTest.1, set env var `USE_TEST_RIG = 1`")

logger.info(f"Running from {COMP_ID}, {'connected to ' + RIG_ID if RIG_ID else 'not connected to a rig'}")


class Rig():
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
    
    def __init__(self, np_rig_idx: Optional[int] = None):
        np_rig_idx = np_rig_idx or RIG_IDX
        if np_rig_idx is None:
            raise ValueError("Rig index not specified and not running on a rig.")
        self.idx = np_rig_idx
        self.id = f"NP.{np_rig_idx}"
    
    @property
    def sync(self) -> str:
        "Hostname for the Sync computer."
        return COMP_ID_TO_HOSTNAME[self.id + "-Sync"]
    SYNC = Sync = sync

    @property
    def mon(self) -> str:
        "Hostname for the Mon computer."
        return COMP_ID_TO_HOSTNAME[self.id + "-Mon"]
    MON = Mon = vidmon = VidMon = VIDMON = mon
    
    @property
    def acq(self) -> str:
        "Hostname for the Acq computer."
        return COMP_ID_TO_HOSTNAME[self.id + "-Acq"]
    ACQ = Acq = acq
    
    @property
    def stim(self) -> str:
        "Hostname for the Stim computer."
        return COMP_ID_TO_HOSTNAME[self.id + "-Stim"]
    STIM = Stim = stim
    
    @property
    def config(self) -> dict[str, Any]:
        "Rig-wide config dict, fetched from ZooKeeper."
        return np_config.from_zk(f"/rigs/{self.id}")

RIG_CONFIG: dict[str, Any] | None = Rig().config if RIG_IDX else None
"Rig-wide config dict, fetched from ZooKeeper, or `None` if not running on a rig."

if __name__ == "__main__":
    import doctest
    doctest.testmod()