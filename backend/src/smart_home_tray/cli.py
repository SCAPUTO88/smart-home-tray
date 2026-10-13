"""Command-line entry point for local diagnostics and JSON Lines sidecar mode."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from smart_home_tray.command_scheduler import CommandScheduler
from smart_home_tray.config import ConfigError, load_config
from smart_home_tray.device_manager import DeviceManager
from smart_home_tray.models import BackendError, device_status_to_public_dict
from smart_home_tray.protocol import JsonLinesServer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="smart-home-tray")
    parser.add_argument("--config", required=True, help="Path to external TOML configuration")
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("list", help="List configured devices without LAN access")
    status = commands.add_parser("status", help="Read device status over the local network")
    status.add_argument("--device", required=True)
    power = commands.add_parser("power", help="Set device power")
    power.add_argument("--device", required=True)
    power_group = power.add_mutually_exclusive_group(required=True)
    power_group.add_argument("--on", action="store_true")
    power_group.add_argument("--off", action="store_true")
    for name, help_text in (
        ("white-brightness", "Set white brightness percentage"),
        ("color-temperature", "Set color temperature percentage"),
        ("color-brightness", "Set color intensity percentage"),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--device", required=True)
        sub.add_argument("--percent", required=True, type=float)
    hsv = commands.add_parser("hsv", help="Set HSV color")
    hsv.add_argument("--device", required=True)
    hsv.add_argument("--hue", required=True, type=float)
    hsv.add_argument("--saturation", required=True, type=float)
    hsv.add_argument("--value", required=True, type=float)
    commands.add_parser("serve", help="Serve JSON Lines requests on stdin/stdout")
    return parser


def _write_status(status: object) -> None:
    print(json.dumps(device_status_to_public_dict(status), ensure_ascii=False, allow_nan=False))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        manager = DeviceManager(config)
        if args.operation == "list":
            print(json.dumps(
                [device_status_to_public_dict(status) for status in manager.list_devices()],
                ensure_ascii=False,
                allow_nan=False,
            ))
            return 0
        if args.operation == "status":
            _write_status(manager.read_state(args.device))
            return 0
        if args.operation == "serve":
            scheduler = CommandScheduler(manager)
            JsonLinesServer(manager, scheduler).run(
                sys.stdin.buffer, sys.stdout.buffer, sys.stderr
            )
            return 0

        scheduler = CommandScheduler(manager)
        scheduler.start()
        try:
            device_id = args.device
            if args.operation == "power":
                future = scheduler.submit_power(device_id, args.on)
            elif args.operation == "white-brightness":
                future = scheduler.submit_white_brightness(device_id, args.percent)
            elif args.operation == "color-temperature":
                future = scheduler.submit_color_temperature(device_id, args.percent)
            elif args.operation == "hsv":
                future = scheduler.submit_hsv(device_id, args.hue, args.saturation, args.value)
            else:
                future = scheduler.submit_color_brightness(device_id, args.percent)
            _write_status(future.result())
        finally:
            scheduler.stop()
        return 0
    except (ConfigError, BackendError) as error:
        if isinstance(error, BackendError):
            print(f"{error.code.value}: operation failed", file=sys.stderr)
        else:
            print(str(error), file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print(f"Command failed: {type(error).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
