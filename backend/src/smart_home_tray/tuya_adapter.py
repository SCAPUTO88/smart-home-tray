"""Small LAN-only wrapper around TinyTuya's generic Device API."""

from __future__ import annotations

import socket
from collections.abc import Callable
from typing import Any

from smart_home_tray.models import BackendError, DeviceConfig, ErrorCode

DeviceFactory = Callable[..., Any]


class TuyaAdapter:
    """Own a TinyTuya connection and expose safe DPS operations."""

    def __init__(self, config: DeviceConfig, device_factory: DeviceFactory | None = None) -> None:
        self._config = config
        self._device = (device_factory or self._default_device_factory())(
            dev_id=config.device_id,
            address=config.address,
            local_key=config.local_key,
            version=config.protocol_version,
            connection_timeout=config.connection_timeout_seconds,
            connection_retry_limit=1,
            connection_retry_delay=0,
            persist=False,
        )

    @staticmethod
    def _default_device_factory() -> DeviceFactory:
        try:
            from tinytuya import Device
        except ImportError as error:
            raise BackendError(ErrorCode.DEVICE_ERROR, "TinyTuya is not installed") from error
        return Device

    @staticmethod
    def _raise_device_error(response: Any) -> None:
        if not isinstance(response, dict) or "Err" not in response:
            return
        code = str(response.get("Err"))
        known_errors = {
            "901": (ErrorCode.DEVICE_OFFLINE, "Device is unreachable"),
            "902": (ErrorCode.TIMEOUT, "Device response timed out"),
            "905": (ErrorCode.DEVICE_OFFLINE, "Device is offline"),
            "914": (ErrorCode.AUTH_FAILED, "Device authentication failed"),
        }
        error_code, message = known_errors.get(
            code, (ErrorCode.DEVICE_ERROR, "Tuya device returned an error")
        )
        raise BackendError(error_code, message)

    @staticmethod
    def _raise_transport_error(error: BaseException) -> None:
        if isinstance(error, (socket.timeout, TimeoutError)):
            raise BackendError(ErrorCode.TIMEOUT, "Device response timed out") from error
        if isinstance(error, OSError):
            raise BackendError(ErrorCode.DEVICE_OFFLINE, "Device is unreachable") from error
        raise BackendError(ErrorCode.DEVICE_ERROR, "Tuya LAN operation failed") from error

    def read_status(self) -> dict[str, object]:
        """Return a validated DPS map from the device's LAN status response."""
        try:
            response = self._device.status()
        except (socket.timeout, TimeoutError, OSError) as error:
            self._raise_transport_error(error)
        except Exception as error:
            self._raise_transport_error(error)

        self._raise_device_error(response)
        if not isinstance(response, dict) or not isinstance(response.get("dps"), dict):
            raise BackendError(ErrorCode.DEVICE_ERROR, "Tuya device returned an invalid status")

        dps: dict[str, object] = {}
        for key, value in response["dps"].items():
            if not isinstance(key, (str, int)) or isinstance(key, bool):
                raise BackendError(ErrorCode.DEVICE_ERROR, "Tuya device returned an invalid DPS index")
            if not isinstance(value, (str, int, float, bool, type(None))):
                raise BackendError(ErrorCode.DEVICE_ERROR, "Tuya device returned an invalid DPS value")
            dps[str(key)] = value
        return dps

    def write_dps(self, dps_index: int, value: object) -> None:
        """Write one DPS and translate TinyTuya's result into a safe error."""
        if isinstance(dps_index, bool) or not isinstance(dps_index, int) or dps_index <= 0:
            raise BackendError(ErrorCode.INVALID_INPUT, "DPS index must be a positive integer")
        if not isinstance(value, (str, int, float, bool)):
            raise BackendError(ErrorCode.INVALID_INPUT, "DPS value must be a scalar")

        try:
            response = self._device.set_value(dps_index, value)
        except (socket.timeout, TimeoutError, OSError) as error:
            self._raise_transport_error(error)
        except Exception as error:
            self._raise_transport_error(error)
        self._raise_device_error(response)
        if response is None:
            raise BackendError(ErrorCode.DEVICE_OFFLINE, "Device did not confirm the command")
