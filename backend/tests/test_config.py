import pytest

from smart_home_tray.config import ConfigError, load_config


def test_load_config_resolves_local_key_from_environment(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '''version = 1
[[devices]]
id = "test-device"
name = "Test light"
address = "192.0.2.10"
protocol_version = 3.5
local_key_env = "TEST_LOCAL_KEY"
[devices.dps]
power = 20
white_brightness = 22
[devices.ranges]
white_brightness = [10, 1000]
''',
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_LOCAL_KEY", "unit-test-key-not-real")

    config = load_config(config_path)

    assert config.devices[0].device_id == "test-device"
    assert config.devices[0].dps.power == 20
    assert config.devices[0].capabilities.white_brightness is True


def test_missing_local_key_environment_variable_is_reported_without_secret(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '''version = 1
[[devices]]
id = "test-device"
name = "Test light"
address = "192.0.2.10"
protocol_version = 3.5
local_key_env = "MISSING_TEST_LOCAL_KEY"
''',
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="MISSING_TEST_LOCAL_KEY") as error:
        load_config(config_path)

    assert "unit-test-key-not-real" not in str(error.value)


def test_config_rejects_duplicate_device_ids(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '''version = 1
[[devices]]
id = "duplicate-id"
name = "First"
address = "192.0.2.10"
protocol_version = 3.5
local_key_env = "TEST_LOCAL_KEY"
[[devices]]
id = "duplicate-id"
name = "Second"
address = "192.0.2.11"
protocol_version = 3.5
local_key_env = "TEST_LOCAL_KEY"
''',
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_LOCAL_KEY", "unit-test-key-not-real")

    with pytest.raises(ConfigError, match="duplicate"):
        load_config(config_path)


def test_config_rejects_invalid_dps_mapping(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '''version = 1
[[devices]]
id = "test-device"
name = "Test light"
address = "192.0.2.10"
protocol_version = 3.5
local_key_env = "TEST_LOCAL_KEY"
[devices.dps]
power = 0
''',
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_LOCAL_KEY", "unit-test-key-not-real")

    with pytest.raises(ConfigError):
        load_config(config_path)
