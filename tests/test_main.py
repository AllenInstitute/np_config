import np_config


def test_zk_online():
    assert np_config.host_responsive(np_config.MINDSCOPE_SERVER)


def test_zk_server_cls():
    np_config.ConfigServer()


def test_zk_file_cls():
    np_config.ConfigFile()


def test_zk_backup():
    backup = np_config.current_zk_backup_path()
    backup.unlink()
    server = np_config.ConfigServer()
    np_config.backup_zk(server)
    assert backup.exists()
    assert all(
        paths in np_config.ConfigFile() for paths in np_config.from_file(backup).keys()
    )


def test_from_file():
    backup = np_config.current_zk_backup_path()
    if backup.exists():
        assert np_config.from_file(backup)


def test_from_zk():
    server = np_config.ConfigServer()
    first_entry = tuple(server.backup.keys())[0]
    assert np_config.from_zk(first_entry)
