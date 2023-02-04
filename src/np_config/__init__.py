import datetime

from np_config.np_config import *
from np_config.rigs import *
from np_config.utils import *

if not LOCAL_ZK_BACKUP_FILE.exists() or datetime.datetime.now() - datetime.datetime.fromtimestamp(
    LOCAL_ZK_BACKUP_FILE.stat().st_mtime
) > datetime.timedelta(
    days=7
):
    backup_zk()
