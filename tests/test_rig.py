from np_config import rigs


def test_rig_mvr_config():
    """Test that the mvr_config property of the Rig class raises no errors."""
    rigs.Rig(2).mvr_config.as_posix() 
    assert True


def test_rig_sync_config():
    """Test that the sync_config property of the Rig class raises no errors."""
    rigs.Rig(2).sync_config.as_posix() 
    assert True


def test_rig_camstim_config():
    """Test that the camstim_config property of the Rig class raises no errors."""
    rigs.Rig(2).camstim_config.as_posix() 
    assert True