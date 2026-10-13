"""Coordinate per-device LAN operations and expose only public device status."""

from __future__ import annotations

import math
import threading
from dataclasses import replace
from typing import Callable

from smart_home_tray.config import AppConfig
from smart_home_tray.models import (
    BackendError,
    ConnectionStatus,
    DeviceConfig,
    DeviceStateQuality,
    DeviceStatus,
    ErrorCode,
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
                self._record_failure(device_id, error)
                raise
            except Exception:
                error = BackendError(ErrorCode.DEVICE_ERROR, "Device status could not be read")
                self._record_failure(device_id, error)
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
                self._record_failure(device_id, error)
                raise
            except Exception:
                error = BackendError(ErrorCode.DEVICE_ERROR, "Power state could not be confirmed")
                self._record_failure(device_id, error)
                raise error from None

            if status.state.quality is DeviceStateQuality.PENDING:
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
            self._states[device_id] = self._make_status(
                updated_config, ConnectionStatus.UNKNOWN, current.state
            )
            return self._states[device_id]

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
        adapter = self._get_adapter_unlocked(device_id)
        dps = adapter.read_status()
        if not isinstance(dps, dict):
            raise BackendError(ErrorCode.DEVICE_ERROR, "Device returned an invalid status")

        previous = self._states[device_id].state
        power = previous.power
        work_mode = previous.work_mode
        pending_power = self._pending_power.get(device_id)
        recognized_value = False

        if config.dps.power is not None and str(config.dps.power) in dps:
            raw_power = dps[str(config.dps.power)]
            if isinstance(raw_power, bool):
                power = raw_power
                recognized_value = True
                if pending_power is not None:
                    self._pending_power.pop(device_id, None)
                    pending_power = None

        if config.dps.work_mode is not None and str(config.dps.work_mode) in dps:
            raw_mode = dps[str(config.dps.work_mode)]
            if isinstance(raw_mode, str):
                work_mode = raw_mode
                recognized_value = True

        quality = (
            DeviceStateQuality.PENDING
            if pending_power is not None
            else DeviceStateQuality.CONFIRMED
            if recognized_value
            else previous.quality
        )
        state = replace(previous, power=power, work_mode=work_mode, quality=quality)
        self._states[device_id] = self._make_status(config, ConnectionStatus.ONLINE, state)
        return self._states[device_id]

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
            if device_id in self._pending_power
            else DeviceStateQuality.OFFLINE
        )
        self._states[device_id] = self._make_status(
            self._configs[device_id],
            ConnectionStatus.OFFLINE,
            replace(current.state, quality=quality),
        )

    def _record_failure(self, device_id: str, error: BackendError) -> None:
        current = self._states[device_id]
        connection = (
            ConnectionStatus.OFFLINE if error.code in _OFFLINE_ERRORS else current.connection
        )
        quality = (
            DeviceStateQuality.PENDING
            if device_id in self._pending_power
            else DeviceStateQuality.OFFLINE
            if connection is ConnectionStatus.OFFLINE
            else current.state.quality
        )
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
