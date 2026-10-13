"""Typed, device-specific contracts shared by the backend modules."""

from __future__ import annotations

import ipaddress
import math
from dataclasses import dataclass, field
from enum import StrEnum


class ErrorCode(StrEnum):
    TIMEOUT = "TIMEOUT"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    AUTH_FAILED = "AUTH_FAILED"
    INVALID_INPUT = "INVALID_INPUT"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    DEVICE_ERROR = "DEVICE_ERROR"


class ConnectionStatus(StrEnum):
    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE = "offline"


class DeviceStateQuality(StrEnum):
    CONFIRMED = "confirmed"
    PENDING = "pending"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class BackendError(Exception):
    """Safe, structured error that can be serialized for CLI/IPC consumers."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class ValueRange:
    """Physical integer DPS range exposed as an interface percentage."""

    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        for name, value in (("minimum", self.minimum), ("maximum", self.maximum)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        if self.maximum <= self.minimum:
            raise ValueError("maximum must be greater than minimum")

    def to_percent(self, raw_value: int | float) -> float:
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise ValueError("raw value must be numeric")
        if not math.isfinite(raw_value):
            raise ValueError("raw value must be finite")
        percent = (raw_value - self.minimum) * 100 / (self.maximum - self.minimum)
        return round(min(100.0, max(0.0, percent)), 2)

    def from_percent(self, percent: int | float) -> int:
        if isinstance(percent, bool) or not isinstance(percent, (int, float)):
            raise ValueError("percent must be numeric")
        if not math.isfinite(percent) or not 0 <= percent <= 100:
            raise ValueError("percent must be between 0 and 100")
        raw_value = self.minimum + (self.maximum - self.minimum) * percent / 100
        return round(raw_value)


@dataclass(frozen=True)
class DPSMap:
    power: int | None = None
    work_mode: int | None = None
    white_brightness: int | None = None
    white_temperature: int | None = None
    hsv: int | None = None
    scene: int | None = None

    def __post_init__(self) -> None:
        indexes = [value for value in self.as_dict().values() if value is not None]
        for name, value in self.as_dict().items():
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ValueError(f"DPS index for {name} must be a positive integer")
        if len(indexes) != len(set(indexes)):
            raise ValueError("DPS indexes must be unique within a device")

    def as_dict(self) -> dict[str, int | None]:
        return {
            "power": self.power,
            "work_mode": self.work_mode,
            "white_brightness": self.white_brightness,
            "white_temperature": self.white_temperature,
            "hsv": self.hsv,
            "scene": self.scene,
        }


@dataclass(frozen=True)
class DeviceCapabilities:
    power: bool
    white_brightness: bool
    color_value: bool
    color_temperature: bool
    scenes: bool


@dataclass(frozen=True)
class HSVColor:
    hue: float
    saturation: float
    value: float

    def __post_init__(self) -> None:
        bounds = (("hue", self.hue, 0, 360), ("saturation", self.saturation, 0, 100), ("value", self.value, 0, 100))
        for name, value, minimum, maximum in bounds:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric")
            if not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError(f"{name} must be between {minimum} and {maximum}")


@dataclass(frozen=True)
class DeviceConfig:
    device_id: str
    name: str
    address: str
    protocol_version: float
    local_key: str = field(repr=False, compare=False)
    dps: DPSMap = field(default_factory=DPSMap)
    white_brightness_range: ValueRange | None = None
    white_temperature_range: ValueRange | None = None
    connection_timeout_seconds: float = 3.0

    def __post_init__(self) -> None:
        if not self.device_id.strip():
            raise ValueError("device_id must not be empty")
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if not self.local_key:
            raise ValueError("local_key must not be empty")
        try:
            ipaddress.ip_address(self.address)
        except ValueError as error:
            raise ValueError("address must be a valid IP address") from error
        if self.protocol_version not in {3.1, 3.2, 3.3, 3.4, 3.5}:
            raise ValueError("protocol_version must be a supported Tuya protocol version")
        if (
            isinstance(self.connection_timeout_seconds, bool)
            or not isinstance(self.connection_timeout_seconds, (int, float))
            or not math.isfinite(self.connection_timeout_seconds)
        ):
            raise ValueError("connection_timeout_seconds must be finite")
        if self.connection_timeout_seconds <= 0:
            raise ValueError("connection_timeout_seconds must be positive")
        if (self.dps.white_brightness is None) != (self.white_brightness_range is None):
            raise ValueError("white_brightness DPS and white_brightness_range must be configured together")
        if (self.dps.white_temperature is None) != (self.white_temperature_range is None):
            raise ValueError("white_temperature DPS and white_temperature_range must be configured together")

    @property
    def capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(
            power=self.dps.power is not None,
            white_brightness=self.dps.white_brightness is not None,
            color_value=self.dps.hsv is not None,
            color_temperature=self.dps.white_temperature is not None,
            scenes=self.dps.scene is not None,
        )


@dataclass(frozen=True)
class LightState:
    power: bool | None = None
    work_mode: str | None = None
    white_brightness_percent: float | None = None
    color_value_percent: float | None = None
    color_temperature_percent: float | None = None
    hsv: HSVColor | None = None
    scene: str | None = None
    quality: DeviceStateQuality = DeviceStateQuality.UNKNOWN


@dataclass(frozen=True)
class DeviceStatus:
    device_id: str
    name: str
    address: str
    protocol_version: float
    capabilities: DeviceCapabilities
    connection: ConnectionStatus = ConnectionStatus.UNKNOWN
    state: LightState = field(default_factory=LightState)
