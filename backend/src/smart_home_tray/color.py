"""Pure color conversions for the Tuya HSV16 wire representation."""

from __future__ import annotations

import colorsys
import math
import re

from smart_home_tray.models import HSVColor


def encode_tuya_hsv(color: HSVColor) -> str:
    """Encode HSV degrees/percentages as Tuya's HHHHSSSSVVVV payload.

    TinyTuya's ``hsv16`` format truncates Hue degrees and Saturation/Value
    tenths of a percent to integers. This encoder uses the same quantization.
    """
    if not isinstance(color, HSVColor):
        raise ValueError("color must be an HSVColor")

    hue = int(color.hue)
    saturation = int(color.saturation * 10)
    value = int(color.value * 10)
    return f"{hue:04x}{saturation:04x}{value:04x}"


def decode_tuya_hsv(payload: object) -> HSVColor:
    """Decode exactly 12 hexadecimal characters into normalized HSV values."""
    if not isinstance(payload, str) or re.fullmatch(r"[0-9a-fA-F]{12}", payload) is None:
        raise ValueError("Tuya HSV payload must contain exactly 12 hexadecimal characters")
    try:
        hue = int(payload[0:4], 16)
        saturation = int(payload[4:8], 16)
        value = int(payload[8:12], 16)
    except ValueError:
        raise ValueError("Tuya HSV payload must contain exactly 12 hexadecimal characters") from None

    if hue > 360 or saturation > 1000 or value > 1000:
        raise ValueError("Tuya HSV component is outside its supported range")
    return HSVColor(hue=hue, saturation=saturation / 10, value=value / 10)


def rgb_to_hsv(red: object, green: object, blue: object) -> HSVColor:
    """Convert 0–255 RGB channels to interface HSV degrees/percentages."""
    channels = (red, green, blue)
    try:
        valid_channels = all(
            not isinstance(channel, bool)
            and isinstance(channel, (int, float))
            and 0 <= channel <= 255
            and math.isfinite(channel)
            for channel in channels
        )
    except (TypeError, OverflowError):
        valid_channels = False
    if not valid_channels:
        raise ValueError("RGB channels must be finite numbers between 0 and 255")

    hue, saturation, value = colorsys.rgb_to_hsv(
        red / 255, green / 255, blue / 255
    )
    return HSVColor(hue=hue * 360, saturation=saturation * 100, value=value * 100)


def hsv_to_rgb(color: HSVColor) -> tuple[int, int, int]:
    """Convert interface HSV to 8-bit RGB, rounding each channel half up."""
    if not isinstance(color, HSVColor):
        raise ValueError("color must be an HSVColor")

    channels = colorsys.hsv_to_rgb(
        color.hue / 360, color.saturation / 100, color.value / 100
    )
    return tuple(math.floor(channel * 255 + 0.5) for channel in channels)
