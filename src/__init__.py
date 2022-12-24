import datetime

from np_config import LOCAL_ZK_BACKUP_FILE, backup_zk

if (
    not LOCAL_ZK_BACKUP_FILE.exists()
    or datetime.datetime.now()
    - datetime.datetime.fromtimestamp(LOCAL_ZK_BACKUP_FILE.stat().st_mtime)
    > datetime.timedelta(days=7)
):
    backup_zk()
