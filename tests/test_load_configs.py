from src.load_configs import load_and_validate, load_configs


def test_loads_real_config():
    config = load_configs()
    assert config is not None
    assert "seasons" in config
    assert "progress" in config


def test_real_config_passes_validation():
    config = load_and_validate()
    assert config["progress"]["season"] == 1
    assert config["posting"]["fph"] >= 1
