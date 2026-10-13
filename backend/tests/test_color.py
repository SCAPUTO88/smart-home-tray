from __future__ import annotations

import math

import pytest

from smart_home_tray.color import decode_tuya_hsv, encode_tuya_hsv, hsv_to_rgb, rgb_to_hsv
from smart_home_tray.models import HSVColor


@pytest.mark.parametrize(
    ("color", "payload"),
    [
        (HSVColor(0, 100, 100), "000003e803e8"),
        (HSVColor(359.9, 99.99, 50.09), "016703e701f4"),
        (HSVColor(210, 64.2, 12.3), "00d20282007b"),
    ],
)
def test_encode_tuya_hsv_matches_tinytuya_hsv16_scales(color, payload):
    assert encode_tuya_hsv(color) == payload


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("000003e803e8", HSVColor(0, 100, 100)),
        ("016803e803e8", HSVColor(360, 100, 100)),
        ("00d20282007b", HSVColor(210, 64.2, 12.3)),
    ],
)
def test_decode_tuya_hsv_uses_degrees_and_percentages(payload, expected):
    assert decode_tuya_hsv(payload) == expected


def test_tuya_hsv_encoding_round_trips_at_wire_precision():
    payload = "00d20282007b"

    assert encode_tuya_hsv(decode_tuya_hsv(payload)) == payload


@pytest.mark.parametrize(
    "payload",
    ["", "0000", "000003e803e8ff", "000003e803eG", "000003e803e8 ", "000 03e803e8", None, 123],
)
def test_decode_tuya_hsv_rejects_malformed_payload(payload):
    with pytest.raises(ValueError):
        decode_tuya_hsv(payload)


@pytest.mark.parametrize("payload", ["016903e803e8", "000003e903e8", "000003e803e9"])
def test_decode_tuya_hsv_rejects_components_outside_tuya_scales(payload):
    with pytest.raises(ValueError):
        decode_tuya_hsv(payload)


@pytest.mark.parametrize(
    ("rgb", "expected"),
    [
        ((255, 0, 0), HSVColor(0, 100, 100)),
        ((0, 255, 0), HSVColor(120, 100, 100)),
        ((0, 0, 255), HSVColor(240, 100, 100)),
        ((0, 0, 0), HSVColor(0, 0, 0)),
        ((255, 255, 255), HSVColor(0, 0, 100)),
    ],
)
def test_rgb_to_hsv_converts_known_colors(rgb, expected):
    assert rgb_to_hsv(*rgb) == expected


@pytest.mark.parametrize(
    ("color", "expected"),
    [
        (HSVColor(0, 100, 100), (255, 0, 0)),
        (HSVColor(120, 100, 100), (0, 255, 0)),
        (HSVColor(240, 100, 100), (0, 0, 255)),
        (HSVColor(360, 100, 100), (255, 0, 0)),
        (HSVColor(0, 0, 0), (0, 0, 0)),
    ],
)
def test_hsv_to_rgb_rounds_channels_to_nearest_integer(color, expected):
    assert hsv_to_rgb(color) == expected


@pytest.mark.parametrize(
    "rgb",
    [
        (True, 0, 0),
        (-1, 0, 0),
        (256, 0, 0),
        (math.nan, 0, 0),
        (math.inf, 0, 0),
        (0, "1", 0),
        (10**1000, 0, 0),
    ],
)
def test_rgb_to_hsv_rejects_invalid_channels(rgb):
    with pytest.raises(ValueError):
        rgb_to_hsv(*rgb)


def test_hsv_to_rgb_requires_hsv_color():
    with pytest.raises(ValueError):
        hsv_to_rgb((0, 100, 100))
