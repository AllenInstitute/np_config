from np_config import rigs


def test_mvr_config():
    """Test that the mvr_config property of the Rig class raises no errors."""
    rigs.Rig(2).mvr_config.as_posix() 
    assert True


def test_sync_config():
    """Test that the sync_config property of the Rig class raises no errors."""
    rigs.Rig(2).sync_config.as_posix() 
    assert True