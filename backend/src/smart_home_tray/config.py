"""Load the local TOML device configuration without leaking secret values."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from smart_home_tray.models import DPSMap, DeviceConfig, ValueRange


class ConfigError(Exception):
    """Configuration error with a message safe to show in logs or CLI output."""


@dataclass(frozen=True)
class AppConfig:
    devices: tuple[DeviceConfig, ...]


def _as_table(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a table")
    return value


def _optional_range(values: Any, label: str) -> ValueRange | None:
    if values is None:
        return None
    if not isinstance(values, list) or len(values) != 2:
        raise ConfigError(f"{label} must contain [minimum, maximum]")
    try:
        return ValueRange(values[0], values[1])
    except (TypeError, ValueError) as error:
        raise ConfigError(f"Invalid {label}: {error}") from error


def load_config(path: str | Path) -> AppConfig:
    """Read a versioned TOML file and resolve Local Keys from environment."""
    config_path = Path(path)
    try:
        with config_path.open("rb") as config_file:
            raw = tomllib.load(config_file)
    except FileNotFoundError as error:
        raise ConfigError(f"Configuration file not found: {config_path}") from error
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"Unable to read configuration file: {error}") from error

    try:
        root = _as_table(raw, "root")
        if root.get("version") != 1:
            raise ConfigError("Configuration version must be 1")
        raw_devices = root.get("devices")
        if not isinstance(raw_devices, list):
            raise ConfigError("devices must be an array of tables")

        devices: list[DeviceConfig] = []
        ids: set[str] = set()
        for index, raw_device in enumerate(raw_devices):
            label = f"devices[{index}]"
            item = _as_table(raw_device, label)
            device_id = item.get("id")
            name = item.get("name")
            address = item.get("address")
            protocol_version = item.get("protocol_version")
            key_env = item.get("local_key_env")
            if not all(isinstance(value, str) and value.strip() for value in (device_id, name, address, key_env)):
                raise ConfigError(f"{label} requires non-empty id, name, address and local_key_env")
            if device_id in ids:
                raise ConfigError(f"duplicate device id in {label}")
            ids.add(device_id)

            local_key = os.environ.get(key_env)
            if not local_key:
                raise ConfigError(f"Environment variable {key_env} is missing or empty")

            dps_table = _as_table(item.get("dps", {}), f"{label}.dps")
            ranges_table = _as_table(item.get("ranges", {}), f"{label}.ranges")
            dps = DPSMap(**dps_table)
            white_brightness_range = _optional_range(
                ranges_table.get("white_brightness"), f"{label}.ranges.white_brightness"
            )
            white_temperature_range = _optional_range(
                ranges_table.get("white_temperature"), f"{label}.ranges.white_temperature"
            )
            timeout = item.get("connection_timeout_seconds", 3.0)
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                raise ConfigError(f"{label}.connection_timeout_seconds must be numeric")

            try:
                device = DeviceConfig(
                    device_id=device_id,
                    name=name,
                    address=address,
                    protocol_version=protocol_version,
                    local_key=local_key,
                    dps=dps,
                    white_brightness_range=white_brightness_range,
                    white_temperature_range=white_temperature_range,
                    connection_timeout_seconds=float(timeout),
                )
            except (TypeError, ValueError) as error:
                raise ConfigError(f"Invalid {label}: {error}") from error
            devices.append(device)
        return AppConfig(devices=tuple(devices))
    except ConfigError:
        raise
    except (TypeError, ValueError) as error:
        raise ConfigError(f"Invalid configuration: {error}") from error
