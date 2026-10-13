from __future__ import annotations

import pytest

from smart_home_tray import cli


def test_help_does_not_load_config_or_create_runtime(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("runtime must not be initialized for help")

    monkeypatch.setattr(cli, "load_config", forbidden)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--help"])
    assert exit_info.value.code == 0
    assert "usage:" in capsys.readouterr().out.lower()


def test_list_uses_catalog_without_reading_devices(monkeypatch, capsys):
    class Manager:
        def list_devices(self):
            return ()

        def read_state(self, device_id):
            raise AssertionError("list must not access LAN")

    monkeypatch.setattr(cli, "load_config", lambda path: object())
    monkeypatch.setattr(cli, "DeviceManager", lambda config: Manager())
    assert cli.main(["--config", "ignored.toml", "list"]) == 0
    assert "[]" in capsys.readouterr().out

