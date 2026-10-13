"""Coordinate per-device LAN operations and expose only public device status."""

from __future__ import annotations

import math
import threading
from dataclasses import replace
from typing import Callable

from smart_home_tray.color import decode_tuya_hsv, encode_tuya_hsv
from smart_home_tray.config import AppConfig
from smart_home_tray.models import (
    BackendError,
    ConnectionStatus,
    DeviceConfig,
    DeviceStateQuality,
    DeviceStatus,
    ErrorCode,
    HSVColor,
    LightState,
)
from smart_home_tray.tuya_adapter import TuyaAdapter

AdapterFactory = Callable[[DeviceConfig], TuyaAdapter]
_OFFLINE_ERRORS = {ErrorCode.TIMEOUT, ErrorCode.DEVICE_OFFLINE, ErrorCode.AUTH_FAILED}


class DeviceManager:
    """Manage a catalog of configured devices without exposing private config."""

    def __init__(
        self,
        config: AppConfig,
        *,
        adapter_factory: AdapterFactory = TuyaAdapter,
        polling_interval_seconds: float = 15.0,
    ) -> None:
        if (
            isinstance(polling_interval_seconds, bool)
            or not isinstance(polling_interval_seconds, (int, float))
            or not math.isfinite(polling_interval_seconds)
            or polling_interval_seconds <= 0
        ):
            raise BackendError(ErrorCode.INVALID_INPUT, "Polling interval must be a positive finite number")

        self._configs: dict[str, DeviceConfig] = {}
        self._adapters: dict[str, TuyaAdapter | None] = {}
        self._states: dict[str, DeviceStatus] = {}
        self._pending_power: dict[str, bool] = {}
        self._last_read_power: dict[str, bool | None] = {}
        self._pending_fields: dict[str, dict[str, object]] = {}
        self._quality_before_pending: dict[str, DeviceStateQuality] = {}
        self._last_read_fields: dict[str, dict[str, object]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._adapter_factory = adapter_factory
        self._polling_interval_seconds = float(polling_interval_seconds)
        self._poll_stop = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._poll_lifecycle_lock = threading.Lock()

        for device in config.devices:
            if device.device_id in self._configs:
                raise BackendError(ErrorCode.INVALID_INPUT, "Duplicate device ID in configuration")
            self._configs[device.device_id] = device
            self._adapters[device.device_id] = None
            self._locks[device.device_id] = threading.Lock()
            self._states[device.device_id] = self._make_status(
                device, ConnectionStatus.UNKNOWN, LightState()
            )

    def list_devices(self) -> tuple[DeviceStatus, ...]:
        """Return public statuses in configuration order."""
        statuses = []
        for device_id in self._configs:
            with self._locks[device_id]:
                statuses.append(self._states[device_id])
        return tuple(statuses)

    def list_device_ids(self) -> tuple[str, ...]:
        """Return stable catalog identities without waiting on per-device LAN locks.

        Catalog membership is immutable after construction; address updates replace
        an existing config entry and never change its Device ID.
        """
        return tuple(self._configs)

    def get_device(self, device_id: str) -> DeviceStatus:
        device_id = self._validate_device_id(device_id)
        with self._locks[device_id]:
            return self._states[device_id]

    def read_state(self, device_id: str) -> DeviceStatus:
        device_id = self._validate_device_id(device_id)
        with self._locks[device_id]:
            try:
                return self._read_state_unlocked(device_id)
            except BackendError as error:
                self._record_failure(device_id, error, read_failure=True)
                raise
            except Exception:
                error = BackendError(ErrorCode.DEVICE_ERROR, "Device status could not be read")
                self._record_failure(device_id, error, read_failure=True)
                raise error from None

    def set_power(self, device_id: str, enabled: bool) -> DeviceStatus:
        device_id = self._validate_device_id(device_id)
        if not isinstance(enabled, bool):
            raise BackendError(ErrorCode.INVALID_INPUT, "Power value must be a boolean")

        with self._locks[device_id]:
            config = self._configs[device_id]
            if not config.capabilities.power or config.dps.power is None:
                raise BackendError(ErrorCode.UNSUPPORTED_CAPABILITY, "Device does not support power control")
            adapter = self._get_adapter_unlocked(device_id)
            previous_state = self._states[device_id].state
            had_previous_pending = device_id in self._pending_power
            previous_pending = self._pending_power.get(device_id)
            self._pending_power[device_id] = enabled
            current = self._states[device_id]
            self._states[device_id] = self._make_status(
                config,
                current.connection,
                replace(current.state, quality=DeviceStateQuality.PENDING),
            )

            try:
                adapter.write_dps(config.dps.power, enabled)
            except BackendError as error:
                if error.code not in {ErrorCode.TIMEOUT, ErrorCode.DEVICE_OFFLINE, ErrorCode.DEVICE_ERROR}:
                    if had_previous_pending:
                        self._pending_power[device_id] = previous_pending
                    else:
                        self._pending_power.pop(device_id, None)
                    self._states[device_id] = self._make_status(
                        config,
                        current.connection,
                        replace(previous_state, quality=(
                            DeviceStateQuality.PENDING
                            if had_previous_pending
                            else previous_state.quality
                        )),
                    )
                self._record_failure(device_id, error)
                raise
            except Exception:
                error = BackendError(ErrorCode.DEVICE_ERROR, "Power command could not be sent")
                self._record_failure(device_id, error)
                raise error from None

            try:
                status = self._read_state_unlocked(device_id)
            except BackendError as error:
                self._record_failure(device_id, error, read_failure=True)
                raise
            except Exception:
                error = BackendError(ErrorCode.DEVICE_ERROR, "Power state could not be confirmed")
                self._record_failure(device_id, error, read_failure=True)
                raise error from None

            if status.state.quality is DeviceStateQuality.PENDING:
                observed_power = self._last_read_power[device_id]
                if observed_power is not None and observed_power is not enabled:
                    raise BackendError(
                        ErrorCode.DEVICE_ERROR,
                        "Power command was sent but the observed state differs from the requested value",
                    )
                raise BackendError(
                    ErrorCode.DEVICE_ERROR,
                    "Power command was sent but the device did not report its power state",
                )
            if status.state.power is not enabled:
                raise BackendError(ErrorCode.DEVICE_ERROR, "Device power state differs from the requested value")
            return status

    def update_address(self, device_id: str, address: str) -> DeviceStatus:
        """Replace the LAN address for a stable device ID and discard its adapter."""
        device_id = self._validate_device_id(device_id)
        if not isinstance(address, str):
            raise BackendError(ErrorCode.INVALID_INPUT, "Device address must be a string")
        with self._locks[device_id]:
            current_config = self._configs[device_id]
            try:
                updated_config = replace(current_config, address=address)
            except (TypeError, ValueError):
                raise BackendError(ErrorCode.INVALID_INPUT, "Device address is invalid") from None

            self._configs[device_id] = updated_config
            self._adapters[device_id] = None
            current = self._states[device_id]
            quality = (
                DeviceStateQuality.PENDING
                if self._has_pending(device_id)
                else DeviceStateQuality.UNKNOWN
            )
            self._states[device_id] = self._make_status(
                updated_config,
                ConnectionStatus.UNKNOWN,
                replace(current.state, quality=quality),
            )
            return self._states[device_id]

    def set_white_brightness(self, device_id: str, percent: object) -> DeviceStatus:
        return self._set_ranged_control(device_id, "white_brightness", percent, "white")

    def set_color_temperature(self, device_id: str, percent: object) -> DeviceStatus:
        return self._set_ranged_control(device_id, "white_temperature", percent, "white")

    def set_hsv(self, device_id: str, hue: object, saturation: object, value: object) -> DeviceStatus:
        device_id = self._validate_device_id(device_id)
        try:
            desired = HSVColor(hue=hue, saturation=saturation, value=value)
            encoded = encode_tuya_hsv(desired)
            desired = decode_tuya_hsv(encoded)
        except (TypeError, ValueError, OverflowError):
            raise BackendError(ErrorCode.INVALID_INPUT, "HSV values are invalid") from None
        return self._set_control(device_id, "hsv", "hsv", encoded, desired, "colour")

    def set_color_brightness(self, device_id: str, percent: object) -> DeviceStatus:
        device_id = self._validate_device_id(device_id)
        self._validate_percent(percent)
        config = self._configs[device_id]
        if not config.capabilities.color_value or config.dps.hsv is None:
            raise BackendError(ErrorCode.UNSUPPORTED_CAPABILITY, "Device does not support color brightness")
        with self._locks[device_id]:
            try:
                self._read_state_unlocked(device_id)
            except BackendError as error:
                self._record_failure(device_id, error, read_failure=True)
                raise
            hsv = self._last_read_fields.get(device_id, {}).get("hsv")
            if not isinstance(hsv, HSVColor):
                raise BackendError(ErrorCode.DEVICE_ERROR, "Current HSV state is unavailable")
            desired = HSVColor(hue=hsv.hue, saturation=hsv.saturation, value=percent)
            encoded = encode_tuya_hsv(desired)
            desired = decode_tuya_hsv(encoded)
            return self._set_control_unlocked(
                device_id, "hsv", "hsv", encoded, desired, "colour", initial_read=False
            )

    def _set_ranged_control(self, device_id: str, dps_name: str, percent: object, mode: str) -> DeviceStatus:
        device_id = self._validate_device_id(device_id)
        self._validate_percent(percent)
        config = self._configs[device_id]
        dps_index = getattr(config.dps, dps_name)
        value_range = (
            config.white_brightness_range if dps_name == "white_brightness"
            else config.white_temperature_range
        )
        if dps_index is None or value_range is None:
            label = "white brightness" if dps_name == "white_brightness" else "color temperature"
            raise BackendError(ErrorCode.UNSUPPORTED_CAPABILITY, f"Device does not support {label}")
        raw = value_range.from_percent(percent)
        expected = value_range.to_percent(raw)
        return self._set_control(device_id, dps_name, dps_name, raw, expected, mode)

    @staticmethod
    def _validate_percent(percent: object) -> None:
        try:
            valid = (
                not isinstance(percent, bool) and isinstance(percent, (int, float))
                and math.isfinite(percent) and 0 <= percent <= 100
            )
        except (TypeError, OverflowError):
            valid = False
        if not valid:
            raise BackendError(ErrorCode.INVALID_INPUT, "Percentage must be finite and between 0 and 100")

    def _set_control(
        self, device_id: str, field_key: str, dps_name: str, raw_value: object,
        expected: object, mode: str,
    ) -> DeviceStatus:
        with self._locks[device_id]:
            return self._set_control_unlocked(
                device_id, field_key, dps_name, raw_value, expected, mode,
            )

    def _set_control_unlocked(
        self, device_id: str, field_key: str, dps_name: str, raw_value: object,
        expected: object, mode: str, *, initial_read: bool = True,
    ) -> DeviceStatus:
        config = self._configs[device_id]
        dps_index = getattr(config.dps, dps_name)
        if dps_index is None:
            raise BackendError(ErrorCode.UNSUPPORTED_CAPABILITY, "Device does not support this lighting control")
        adapter = self._get_adapter_unlocked(device_id)
        if initial_read:
            try:
                self._read_state_unlocked(device_id)
            except BackendError as error:
                self._record_failure(device_id, error, read_failure=True)
                raise

        mode_index = config.dps.work_mode
        changed_mode = False
        if mode_index is not None and self._states[device_id].state.work_mode != mode:
            self._set_pending_field(device_id, "work_mode", mode)
            try:
                adapter.write_dps(mode_index, mode)
                changed_mode = True
            except BackendError as error:
                self._handle_write_error(device_id, "work_mode", error)
                raise
            except Exception:
                error = BackendError(ErrorCode.DEVICE_ERROR, "Lighting mode could not be changed")
                self._record_failure(device_id, error)
                raise error from None

        already_observed = self._last_read_fields.get(device_id, {}).get(field_key)
        mode_is_confirmed = mode_index is None or self._last_read_fields.get(device_id, {}).get("work_mode") == mode
        if already_observed == expected and mode_is_confirmed:
            return self._states[device_id]

        self._set_pending_field(device_id, field_key, expected)
        try:
            adapter.write_dps(dps_index, raw_value)
        except BackendError as error:
            self._handle_write_error(device_id, field_key, error)
            if changed_mode:
                self._best_effort_read(device_id)
            raise
        except Exception:
            error = BackendError(ErrorCode.DEVICE_ERROR, "Lighting command could not be sent")
            self._record_failure(device_id, error)
            if changed_mode:
                self._best_effort_read(device_id)
            raise error from None

        try:
            status = self._read_state_unlocked(device_id)
        except BackendError as error:
            self._record_failure(device_id, error, read_failure=True)
            raise
        observed = self._last_read_fields.get(device_id, {}).get(field_key)
        if observed != expected:
            detail = "differs" if observed is not None else "was not reported"
            raise BackendError(ErrorCode.DEVICE_ERROR, f"Lighting command was sent but the observed value {detail}")
        if mode_index is not None and self._last_read_fields.get(device_id, {}).get("work_mode") != mode:
            raise BackendError(ErrorCode.DEVICE_ERROR, "Lighting command was sent but the requested mode was not confirmed")
        return status

    def _set_pending_field(self, device_id: str, field: str, value: object) -> None:
        if not self._has_pending(device_id):
            self._quality_before_pending[device_id] = self._states[device_id].state.quality
        self._pending_fields.setdefault(device_id, {})[field] = value
        current = self._states[device_id]
        self._states[device_id] = self._make_status(
            self._configs[device_id], current.connection,
            replace(current.state, quality=DeviceStateQuality.PENDING),
        )

    def _handle_write_error(self, device_id: str, field: str, error: BackendError) -> None:
        if error.code in {ErrorCode.INVALID_INPUT, ErrorCode.UNSUPPORTED_CAPABILITY}:
            pending = self._pending_fields.get(device_id, {})
            pending.pop(field, None)
            if not pending:
                self._pending_fields.pop(device_id, None)
        self._record_failure(device_id, error)

    def _best_effort_read(self, device_id: str) -> None:
        try:
            self._read_state_unlocked(device_id)
        except BackendError as error:
            self._record_failure(device_id, error, read_failure=True)

    @property
    def polling_running(self) -> bool:
        thread = self._poll_thread
        return thread is not None and thread.is_alive()

    def start_polling(self) -> None:
        """Start periodic LAN reads; polling is never started by the constructor."""
        with self._poll_lifecycle_lock:
            if self._poll_thread is not None and self._poll_thread.is_alive():
                return
            self._poll_stop.clear()
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name="smart-home-tray-device-polling",
                daemon=True,
            )
            self._poll_thread.start()

    def stop_polling(self) -> None:
        """Signal the polling worker to stop and wait for its bounded LAN call."""
        with self._poll_lifecycle_lock:
            thread = self._poll_thread
            if thread is None:
                return
            self._poll_stop.set()
            if thread is not threading.current_thread():
                thread.join()
            self._poll_thread = None

    def poll_once(self) -> None:
        """Run one isolated sync cycle, useful for explicit callers and tests."""
        for device_id in self._configs:
            try:
                self.read_state(device_id)
            except BackendError:
                continue

    def _poll_loop(self) -> None:
        while not self._poll_stop.wait(self._polling_interval_seconds):
            self.poll_once()

    def _read_state_unlocked(self, device_id: str) -> DeviceStatus:
        config = self._configs[device_id]
        self._last_read_power[device_id] = None
        adapter = self._get_adapter_unlocked(device_id)
        dps = adapter.read_status()
        if not isinstance(dps, dict):
            raise BackendError(ErrorCode.DEVICE_ERROR, "Device returned an invalid status")

        previous = self._states[device_id].state
        power = previous.power
        work_mode = previous.work_mode
        pending_power = self._pending_power.get(device_id)
        observed: dict[str, object] = {}
        recognized_value = False

        if config.dps.power is not None and str(config.dps.power) in dps:
            raw_power = dps[str(config.dps.power)]
            if isinstance(raw_power, bool):
                power = raw_power
                self._last_read_power[device_id] = raw_power
                recognized_value = True
                if pending_power is not None and raw_power is pending_power:
                    self._pending_power.pop(device_id, None)
                    pending_power = None

        if config.dps.work_mode is not None and str(config.dps.work_mode) in dps:
            raw_mode = dps[str(config.dps.work_mode)]
            if isinstance(raw_mode, str):
                work_mode = raw_mode
                observed["work_mode"] = raw_mode
                recognized_value = True

        white = previous.white_brightness_percent
        if config.dps.white_brightness is not None and config.white_brightness_range is not None:
            value = self._read_numeric_range(dps, config.dps.white_brightness, config.white_brightness_range)
            if value is not None:
                white = value
                observed["white_brightness"] = value
                recognized_value = True

        temperature = previous.color_temperature_percent
        if config.dps.white_temperature is not None and config.white_temperature_range is not None:
            value = self._read_numeric_range(dps, config.dps.white_temperature, config.white_temperature_range)
            if value is not None:
                temperature = value
                observed["white_temperature"] = value
                recognized_value = True

        color_value = previous.color_value_percent
        hsv = previous.hsv
        if config.dps.hsv is not None:
            raw_hsv = dps.get(str(config.dps.hsv))
            try:
                decoded = decode_tuya_hsv(raw_hsv)
            except (TypeError, ValueError, OverflowError):
                pass
            else:
                hsv = decoded
                color_value = decoded.value
                observed["hsv"] = decoded
                recognized_value = True

        scene = previous.scene
        if config.dps.scene is not None:
            raw_scene = dps.get(str(config.dps.scene))
            if isinstance(raw_scene, str):
                scene = raw_scene
                observed["scene"] = raw_scene
                recognized_value = True

        self._last_read_fields[device_id] = observed
        pending_fields = self._pending_fields.get(device_id, {})
        for field, expected in tuple(pending_fields.items()):
            if field in observed and observed[field] == expected:
                pending_fields.pop(field, None)
        if not pending_fields:
            self._pending_fields.pop(device_id, None)
        if not self._has_pending(device_id):
            self._quality_before_pending.pop(device_id, None)

        quality = (
            DeviceStateQuality.PENDING
            if pending_power is not None or self._pending_fields.get(device_id)
            else DeviceStateQuality.CONFIRMED
            if recognized_value
            else previous.quality
        )
        state = replace(
            previous, power=power, work_mode=work_mode,
            white_brightness_percent=white,
            color_temperature_percent=temperature,
            color_value_percent=color_value, hsv=hsv, scene=scene,
            quality=quality,
        )
        self._states[device_id] = self._make_status(config, ConnectionStatus.ONLINE, state)
        return self._states[device_id]

    @staticmethod
    def _read_numeric_range(dps: dict[str, object], index: int, value_range: object) -> float | None:
        raw = dps.get(str(index))
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        try:
            if not math.isfinite(raw) or not value_range.minimum <= raw <= value_range.maximum:
                return None
            return value_range.to_percent(raw)
        except (TypeError, ValueError, OverflowError):
            return None

    def _has_pending(self, device_id: str) -> bool:
        return device_id in self._pending_power or bool(self._pending_fields.get(device_id))

    def _get_adapter_unlocked(self, device_id: str) -> TuyaAdapter:
        adapter = self._adapters[device_id]
        if adapter is not None:
            return adapter
        try:
            adapter = self._adapter_factory(self._configs[device_id])
        except BackendError as error:
            self._mark_adapter_initialization_failure(device_id)
            raise
        except Exception:
            self._mark_adapter_initialization_failure(device_id)
            raise BackendError(ErrorCode.DEVICE_ERROR, "Device connection could not be initialized") from None
        self._adapters[device_id] = adapter
        return adapter

    def _mark_adapter_initialization_failure(self, device_id: str) -> None:
        current = self._states[device_id]
        quality = (
            DeviceStateQuality.PENDING
            if self._has_pending(device_id)
            else DeviceStateQuality.OFFLINE
        )
        self._states[device_id] = self._make_status(
            self._configs[device_id],
            ConnectionStatus.OFFLINE,
            replace(current.state, quality=quality),
        )

    def _record_failure(
        self,
        device_id: str,
        error: BackendError,
        *,
        read_failure: bool = False,
    ) -> None:
        current = self._states[device_id]
        connection = (
            ConnectionStatus.OFFLINE if error.code in _OFFLINE_ERRORS else current.connection
        )
        if self._has_pending(device_id):
            quality = DeviceStateQuality.PENDING
        elif connection is ConnectionStatus.OFFLINE:
            quality = DeviceStateQuality.OFFLINE
            self._quality_before_pending.pop(device_id, None)
        elif read_failure:
            quality = DeviceStateQuality.UNKNOWN
            self._quality_before_pending.pop(device_id, None)
        elif current.state.quality is DeviceStateQuality.PENDING:
            quality = self._quality_before_pending.pop(
                device_id, DeviceStateQuality.UNKNOWN
            )
        else:
            quality = current.state.quality
            self._quality_before_pending.pop(device_id, None)
        state = replace(current.state, quality=quality)
        self._states[device_id] = self._make_status(self._configs[device_id], connection, state)

    def _validate_device_id(self, device_id: str) -> str:
        if not isinstance(device_id, str) or not device_id.strip() or device_id not in self._configs:
            raise BackendError(ErrorCode.INVALID_INPUT, "Unknown device ID")
        return device_id

    @staticmethod
    def _make_status(
        config: DeviceConfig,
        connection: ConnectionStatus,
        state: LightState,
    ) -> DeviceStatus:
        return DeviceStatus(
            device_id=config.device_id,
            name=config.name,
            address=config.address,
            protocol_version=config.protocol_version,
            capabilities=config.capabilities,
            connection=connection,
            state=state,
        )
