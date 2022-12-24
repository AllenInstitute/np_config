import contextlib
import dataclasses
import logging.config
import os
import pathlib
import random
from typing import Dict, Mapping

import pytest

import np_config

logging.config.dictConfig(np_config.fetch("/np_defaults/logging"))

key = "test"
known_zk_keys = ("/mpe_defaults/logging", "/mpe_defaults/configuration")


@pytest.fixture(scope="function")
def test_dict() -> Dict[str, int]:
    return {key: random.randint(0, 100)}


@pytest.fixture(scope="module")
def test_zk():
    with np_config.ConfigZK() as zk:
        yield zk
    with contextlib.suppress(KeyError):
        zk[key] = {}


def test_zk_online():
    assert np_config.host_responsive(np_config.MINDSCOPE_SERVER)


def test_to_file_from_file(tmp_path, test_dict):
    for suffix in (".json", ".yaml"):
        file = tmp_path / f"test{suffix}"
        np_config.to_file(test_dict, file)
        assert np_config.from_file(file) == test_dict


def test_to_zk_from_zk(test_dict):
    np_config.to_zk(test_dict, path=key)
    assert np_config.from_zk(key) == test_dict
    np_config.to_zk({}, path=key)


def standard_dict_methods(dict, value):
    dict[key] = value
    assert dict[key] == value
    del dict[key]
    assert pytest.raises(KeyError, dict.__getitem__, key)
    assert dict.get(key) is None
    assert dict.get(key, 1) is 1


def test_zk_cls(test_zk, test_dict):
    standard_dict_methods(test_zk, test_dict)


def standard_file_dict_methods(dict, value):
    dict[key] = value
    assert np_config.from_file(dict.file)[key] == value
    del dict[key]
    assert np_config.from_file(dict.file) == {}
    # test non-string key - not valid .json
    if dict.file.suffix != ".json":
        dict[0] = value
        assert np_config.from_file(dict.file)[0] == value


def test_file_cls(tmp_path, test_dict):
    file = tmp_path / "test.json"
    test_file = np_config.ConfigFile(file)
    standard_dict_methods(test_file, test_dict)
    standard_file_dict_methods(test_file, test_dict)
    file = tmp_path / "test.yaml"
    test_file = np_config.ConfigFile(file)
    standard_file_dict_methods(test_file, test_dict)


def test_recorded_cls(tmp_path, test_dict):
    file = tmp_path / "test.yaml"
    test_recorded = np_config.RecordedZK(record_file=file)
    test_recorded[key] = test_dict
    assert test_recorded[key] == test_dict
    assert np_config.from_file(file)[key] == test_dict
    # items can't be deleted from record on file
    del test_recorded[key]
    assert np_config.from_file(file)[key] == test_dict
    # but should be deleted from the monitored dict
    assert pytest.raises(KeyError, test_recorded.__getitem__, key)

    test_recorded = np_config.RecordedZK(record_file=file)
    # previously-accessed items should be restored from file, if file is re-used
    assert np_config.from_file(file)[key] == test_dict
    # accessed item should be recorded on file
    _ = test_recorded[known_zk_keys[0]]
    assert np_config.from_file(file)[known_zk_keys[0]] == _
    # items not accessed should not be recorded on file
    assert known_zk_keys[1] not in np_config.from_file(file).keys()
    # record-keeping can be disabled
    with test_recorded.no_record():
        assert test_recorded[known_zk_keys[1]]
    assert known_zk_keys[1] not in np_config.from_file(file).keys()


def test_session_zk_record(tmp_path, test_dict):
    file = tmp_path / "test.yaml"
    # mod the path the record is written to
    np_config.SESSION_ZK_RECORD.record.file = file
    np_config.to_zk(test_dict, path=key)
    _ = np_config.SESSION_ZK_RECORD[key]
    assert (
        np_config.from_file(np_config.SESSION_ZK_RECORD.record.file)[key] == test_dict
    )


def test_backup_zk(tmp_path):
    backup = tmp_path / "test_backup.json"
    np_config.backup_zk(backup)
    assert backup.exists()
    server = np_config.ConfigZK()
    with server:
        assert all(server[paths] for paths in np_config.from_file(backup).keys())


def backed_up_zk(tmp_path, test_dict):
    backup = tmp_path / "test_backedup.json"
    np_config.to_file(test_dict, backup)
    test_zk = np_config.BackedUpZK(backup_file=backup)

    def using_local_backup(obj):
        return not hasattr(obj, "hosts")

    # known keys should be accessible either way
    assert test_zk[known_zk_keys[0]]

    # force local backup to be used:
    test_zk = np_config.BackedUpZK(hosts="wrong:0000", backup_file=backup)
    assert using_local_backup(test_zk)
    assert test_zk[known_zk_keys[0]]


# test_zk_backup()
