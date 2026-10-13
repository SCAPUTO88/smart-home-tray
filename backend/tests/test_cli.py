from __future__ import annotations

import pytest
from concurrent.futures import Future

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


@pytest.mark.parametrize("operation", ["status", "initialization"])
def test_unexpected_failures_are_sanitized_and_return_nonzero(monkeypatch, capsys, operation):
    secret = "fake-sensitive-key-for-regression"
    monkeypatch.setattr(cli, "load_config", lambda path: object())

    class Manager:
        def list_devices(self):
            return ()

        def read_state(self, device_id):
            raise RuntimeError(secret)

    if operation == "initialization":
        monkeypatch.setattr(cli, "DeviceManager", lambda config: (_ for _ in ()).throw(RuntimeError(secret)))
        argv = ["--config", "ignored.toml", "list"]
    else:
        monkeypatch.setattr(cli, "DeviceManager", lambda config: Manager())
        argv = ["--config", "ignored.toml", "status", "--device", "lamp-a"]

    assert cli.main(argv) != 0
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert "Traceback" not in captured.err
    assert "unexpectedly" in captured.err
def test_unexpected_write_failure_still_stops_scheduler(monkeypatch, capsys):
    stopped = []
    monkeypatch.setattr(cli, "load_config", lambda path: object())

    class Manager:
        def list_devices(self):
            return ()

    class Scheduler:
        def __init__(self, manager):
            pass

        def start(self):
            pass

        def submit_power(self, *args):
            future = Future()
            future.set_exception(RuntimeError("fake-sensitive-key"))
            return future

        def stop(self):
            stopped.append(True)
            return True

    monkeypatch.setattr(cli, "DeviceManager", lambda config: Manager())
    monkeypatch.setattr(cli, "CommandScheduler", Scheduler)
    assert cli.main(["--config", "ignored.toml", "power", "--device", "lamp-a", "--on"]) != 0
    assert stopped == [True]
    captured = capsys.readouterr()
    assert "fake-sensitive-key" not in captured.out + captured.err

