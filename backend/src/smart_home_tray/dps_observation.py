"""Pure interpretation of configured DPS values without applying device state."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

from smart_home_tray.color import decode_tuya_hsv
from smart_home_tray.models import DeviceConfig, HSVColor


@dataclass(frozen=True)
class DPSObservation:
    """Semantically recognized values from one DPS map, with no manager effects."""

    power: bool | None = None
    work_mode: str | None = None
    white_brightness_percent: float | None = None
    color_temperature_percent: float | None = None
    hsv: HSVColor | None = None
    scene: str | None = None
    observed: frozenset[str] = frozenset()


def observe_dps(config: DeviceConfig, dps: Mapping[object, object]) -> DPSObservation:
    """Interpret known fields using the same type/range rules as DeviceManager."""
    if not isinstance(dps, Mapping):
        return DPSObservation()

    observed: dict[str, object] = {}
    power = None
    mode = None
    white = None
    temperature = None
    hsv = None
    scene = None

    if config.dps.power is not None:
        raw = dps.get(str(config.dps.power))
        if isinstance(raw, bool):
            power = raw
            observed["power"] = raw

    if config.dps.work_mode is not None:
        raw = dps.get(str(config.dps.work_mode))
        if isinstance(raw, str):
            mode = raw
            observed["work_mode"] = raw

    if config.dps.white_brightness is not None and config.white_brightness_range is not None:
        white = _read_numeric_range(dps, config.dps.white_brightness, config.white_brightness_range)
        if white is not None:
            observed["white_brightness"] = white

    if config.dps.white_temperature is not None and config.white_temperature_range is not None:
        temperature = _read_numeric_range(
            dps, config.dps.white_temperature, config.white_temperature_range
        )
        if temperature is not None:
            observed["white_temperature"] = temperature

    if config.dps.hsv is not None:
        try:
            hsv = decode_tuya_hsv(dps.get(str(config.dps.hsv)))
        except (TypeError, ValueError, OverflowError):
            pass
        else:
            observed["hsv"] = hsv

    if config.dps.scene is not None:
        raw = dps.get(str(config.dps.scene))
        if isinstance(raw, str):
            scene = raw
            observed["scene"] = raw

    return DPSObservation(
        power=power,
        work_mode=mode,
        white_brightness_percent=white,
        color_temperature_percent=temperature,
        hsv=hsv,
        scene=scene,
        observed=frozenset(observed),
    )


def _read_numeric_range(dps: Mapping[object, object], index: int, value_range: object) -> float | None:
    raw = dps.get(str(index))
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    try:
        if not math.isfinite(raw) or not value_range.minimum <= raw <= value_range.maximum:
            return None
        return value_range.to_percent(raw)
    except (TypeError, ValueError, OverflowError):
        return None
