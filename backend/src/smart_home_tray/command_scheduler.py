"""Serialize normalized device commands and coalesce continuous control bursts."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from smart_home_tray.models import BackendError, DeviceStatus, ErrorCode

DEFAULT_COALESCING_WINDOW_SECONDS = 0.150
DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 10.0


class _DeviceManager(Protocol):
    def list_device_ids(self) -> tuple[str, ...]: ...

    def set_white_brightness(self, device_id: str, percent: object) -> DeviceStatus: ...

    def set_color_temperature(self, device_id: str, percent: object) -> DeviceStatus: ...

    def set_hsv(self, device_id: str, hue: object, saturation: object, value: object) -> DeviceStatus: ...

    def set_color_brightness(self, device_id: str, percent: object) -> DeviceStatus: ...

    def set_power(self, device_id: str, enabled: bool) -> DeviceStatus: ...


class _CommandKind(Enum):
    WHITE_BRIGHTNESS = "white_brightness"
    COLOR_TEMPERATURE = "color_temperature"
    HSV = "hsv"
    COLOR_BRIGHTNESS = "color_brightness"
    POWER = "power"

    @property
    def continuous(self) -> bool:
        return self is not _CommandKind.POWER


@dataclass
class _QueuedCommand:
    kind: _CommandKind
    device_id: str
    arguments: tuple[object, ...]
    future: Future[DeviceStatus]
    ready_at: float
    bypass_window: bool = False


class CommandScheduler:
    """Background command scheduler with per-device order and bounded coalescing.

    Call :meth:`start` before submitting commands. Each configured device gets
    one worker; network operations happen without holding the scheduler's
    condition lock. The DeviceManager remains responsible for device locks and
    physical-state confirmation.
    """

    def __init__(
        self,
        device_manager: _DeviceManager,
        *,
        coalescing_window_seconds: float = DEFAULT_COALESCING_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            isinstance(coalescing_window_seconds, bool)
            or not isinstance(coalescing_window_seconds, (int, float))
            or not math.isfinite(coalescing_window_seconds)
            or coalescing_window_seconds < 0
        ):
            raise ValueError("coalescing window must be a finite non-negative number")
        if not callable(clock):
            raise TypeError("clock must be callable")

        self._device_manager = device_manager
        self._coalescing_window_seconds = float(coalescing_window_seconds)
        self._clock = clock
        self._condition = threading.Condition()
        self._queues: dict[str, deque[_QueuedCommand]] = {}
        self._workers: dict[str, threading.Thread] = {}
        self._last_continuous_start: dict[str, float] = {}
        self._started = False
        self._closed = False

    def start(self) -> None:
        """Start one worker per configured device; repeated calls are harmless."""
        with self._condition:
            if self._closed:
                raise RuntimeError("command scheduler is stopped")
            if self._started:
                return

        device_ids = self._device_manager.list_device_ids()
        with self._condition:
            if self._closed:
                raise RuntimeError("command scheduler is stopped")
            if self._started:
                return
            self._started = True
            for device_id in device_ids:
                self._queues[device_id] = deque()
                worker = threading.Thread(
                    target=self._worker,
                    args=(device_id,),
                    name=f"smart-home-tray-command-{device_id}",
                    daemon=False,
                )
                self._workers[device_id] = worker
                worker.start()

    def stop(self, *, timeout_seconds: float = DEFAULT_SHUTDOWN_TIMEOUT_SECONDS) -> bool:
        """Close submission, cancel queued work, and wait boundedly for active calls.

        In-flight DeviceManager operations are allowed to finish. Returns
        ``False`` if a worker is still in such an operation after the timeout;
        a later call can join it again. Queued Futures are cancelled.
        """
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds < 0
        ):
            raise ValueError("shutdown timeout must be a finite non-negative number")

        queued_futures: list[Future[DeviceStatus]] = []
        with self._condition:
            self._closed = True
            for queue in self._queues.values():
                queued_futures.extend(command.future for command in queue)
                queue.clear()
            workers = tuple(self._workers.values())
            self._condition.notify_all()

        for future in queued_futures:
            future.cancel()

        deadline = time.monotonic() + float(timeout_seconds)
        current_thread = threading.current_thread()
        for worker in workers:
            if worker is current_thread:
                continue
            remaining = max(0.0, deadline - time.monotonic())
            worker.join(timeout=remaining)
        return all(not worker.is_alive() for worker in workers)

    def submit_white_brightness(self, device_id: str, percent: object) -> Future[DeviceStatus]:
        return self._submit(_CommandKind.WHITE_BRIGHTNESS, device_id, percent)

    def submit_color_temperature(self, device_id: str, percent: object) -> Future[DeviceStatus]:
        return self._submit(_CommandKind.COLOR_TEMPERATURE, device_id, percent)

    def submit_hsv(
        self, device_id: str, hue: object, saturation: object, value: object
    ) -> Future[DeviceStatus]:
        return self._submit(_CommandKind.HSV, device_id, hue, saturation, value)

    def submit_color_brightness(self, device_id: str, percent: object) -> Future[DeviceStatus]:
        return self._submit(_CommandKind.COLOR_BRIGHTNESS, device_id, percent)

    def submit_power(self, device_id: str, enabled: bool) -> Future[DeviceStatus]:
        return self._submit(_CommandKind.POWER, device_id, enabled)

    def _submit(self, kind: _CommandKind, device_id: str, *arguments: object) -> Future[DeviceStatus]:
        future: Future[DeviceStatus] = Future()
        superseded: Future[DeviceStatus] | None = None
        with self._condition:
            if not self._started:
                raise RuntimeError("command scheduler is not started")
            if self._closed:
                raise RuntimeError("command scheduler is stopped")
            queue = self._queues.get(device_id) if isinstance(device_id, str) else None
            if queue is None:
                raise BackendError(ErrorCode.INVALID_INPUT, "Unknown device ID")

            now = self._clock()
            if kind.continuous and queue and queue[-1].kind is kind:
                previous = queue.pop()
                superseded = previous.future
                ready_at = previous.ready_at
            else:
                ready_at = now + self._coalescing_window_seconds if kind.continuous else now

            if kind is _CommandKind.POWER:
                # Flush every continuous segment already ordered before this barrier.
                for previous in queue:
                    if previous.kind.continuous:
                        previous.ready_at = min(previous.ready_at, now)
                        previous.bypass_window = True

            queue.append(_QueuedCommand(kind, device_id, tuple(arguments), future, ready_at))
            self._condition.notify_all()

        if superseded is not None:
            superseded.cancel()
        return future

    def _worker(self, device_id: str) -> None:
        while True:
            with self._condition:
                queue = self._queues[device_id]
                while True:
                    if self._closed:
                        return
                    if not queue:
                        self._condition.wait()
                        continue

                    command = queue[0]
                    if command.future.cancelled():
                        queue.popleft()
                        self._condition.notify_all()
                        continue

                    ready_at = command.ready_at
                    if command.kind.continuous and not command.bypass_window:
                        previous_start = self._last_continuous_start.get(device_id)
                        if previous_start is not None:
                            ready_at = max(
                                ready_at,
                                previous_start + self._coalescing_window_seconds,
                            )
                    remaining = ready_at - self._clock()
                    if remaining > 0:
                        self._condition.wait(timeout=remaining)
                        continue

                    queue.popleft()
                    if not command.future.set_running_or_notify_cancel():
                        continue
                    if command.kind.continuous:
                        self._last_continuous_start[device_id] = self._clock()
                    break

            try:
                result = self._execute(command)
            except Exception as error:
                command.future.set_exception(error)
            else:
                command.future.set_result(result)

    def _execute(self, command: _QueuedCommand) -> DeviceStatus:
        manager = self._device_manager
        if command.kind is _CommandKind.WHITE_BRIGHTNESS:
            return manager.set_white_brightness(command.device_id, *command.arguments)
        if command.kind is _CommandKind.COLOR_TEMPERATURE:
            return manager.set_color_temperature(command.device_id, *command.arguments)
        if command.kind is _CommandKind.HSV:
            return manager.set_hsv(command.device_id, *command.arguments)
        if command.kind is _CommandKind.COLOR_BRIGHTNESS:
            return manager.set_color_brightness(command.device_id, *command.arguments)
        if command.kind is _CommandKind.POWER:
            return manager.set_power(command.device_id, *command.arguments)
        raise BackendError(ErrorCode.INVALID_INPUT, "Unsupported scheduled command")
