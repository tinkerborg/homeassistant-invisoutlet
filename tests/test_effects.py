"""Tests for the Aura effect-mode registry (pure logic, no HA setup)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from invisoutlet import ColorEffect

from custom_components.invisoutlet.const import (
    EFFECT_STATIC_COLOR,
    EFFECT_STATIC_TEMPERATURE,
)
from custom_components.invisoutlet.effects import (
    PIXEL_COUNT,
    ApplyContext,
    PixelKind,
    PixelState,
    get_effect_mode,
    mode_label,
)


def _pixel(**overrides: object) -> PixelState:
    """A PixelState with sensible defaults."""
    values = {
        "on": True,
        "hue": 200,
        "saturation": 60,
        "brightness": 80,
        "temperature": 4000,
    }
    values.update(overrides)
    return PixelState(**values)  # type: ignore[arg-type]


def test_get_effect_mode_known_and_fallback() -> None:
    """Known values resolve; unknown falls back to Static Color."""
    assert get_effect_mode("rainbow").value == "rainbow"
    assert get_effect_mode("nonsense").value == EFFECT_STATIC_COLOR
    assert get_effect_mode(None).value == EFFECT_STATIC_COLOR  # type: ignore[arg-type]


def test_device_mode_values() -> None:
    """Each mode reports the device mode int it drives (1/2 static, 3-7 effects)."""
    assert get_effect_mode(EFFECT_STATIC_COLOR).device_mode == 1
    assert get_effect_mode(EFFECT_STATIC_TEMPERATURE).device_mode == 2
    assert get_effect_mode("breathing").device_mode == int(ColorEffect.BREATHING)
    assert get_effect_mode("rainbow").device_mode == int(ColorEffect.RAINBOW)


def test_mode_label() -> None:
    """A device mode int maps back to a human effect-type label (None if unknown)."""
    assert mode_label(int(ColorEffect.RAINBOW)) == "Rainbow"
    assert mode_label(int(ColorEffect.COLOR_CYCLE)) == "Color Cycle"
    assert mode_label(int(ColorEffect.STARRY_NIGHT)) == "Starry Night"
    assert mode_label(99) is None


def test_static_color_layout() -> None:
    """Static Color has no speed and one forced-on color pixel."""
    mode = get_effect_mode(EFFECT_STATIC_COLOR)
    assert mode.has_speed is False
    assert mode.has_random is False
    specs = mode.pixels(random=False)
    assert len(specs) == 1
    assert specs[0].forced_on is True
    assert specs[0].kind is PixelKind.HS


def test_static_temperature_layout() -> None:
    """Static Temperature exposes one temperature pixel per LED."""
    mode = get_effect_mode(EFFECT_STATIC_TEMPERATURE)
    specs = mode.pixels(random=False)
    assert len(specs) == PIXEL_COUNT
    assert all(s.kind is PixelKind.TEMPERATURE for s in specs)


def test_randomizable_layout_random_vs_fixed() -> None:
    """Random collapses to a single brightness pixel; otherwise nine colors."""
    mode = get_effect_mode("color_cycle")  # required=2
    assert mode.has_random is True

    random_specs = mode.pixels(random=True)
    assert len(random_specs) == 1
    assert random_specs[0].kind is PixelKind.BRIGHTNESS
    assert random_specs[0].forced_on is True

    fixed_specs = mode.pixels(random=False)
    assert len(fixed_specs) == PIXEL_COUNT
    # color_cycle forces the first two pixels on.
    assert [s.forced_on for s in fixed_specs[:3]] == [True, True, False]


def test_starry_night_layout() -> None:
    """Starry Night is a Background + Stars pair when not randomised."""
    mode = get_effect_mode("starry_night")
    assert [s.name for s in mode.pixels(random=False)] == ["Background", "Stars"]
    assert mode.pixels(random=True)[0].name == "Brightness"


def test_spec_out_of_range_returns_none() -> None:
    """spec() returns None past the active pixel count."""
    mode = get_effect_mode(EFFECT_STATIC_COLOR)
    assert mode.spec(0, random=False) is not None
    assert mode.spec(5, random=False) is None


async def test_apply_static_color_pushes_hsv() -> None:
    """Static Color pushes a single HSV color to the array."""
    coordinator = AsyncMock()
    ctx = ApplyContext(
        coordinator=coordinator, light=5, pixels=[_pixel()], speed=0, random=False
    )
    await get_effect_mode(EFFECT_STATIC_COLOR).apply(ctx)
    coordinator.async_set_color_hsv.assert_awaited_once_with(
        5, hue=200, saturation=60, brightness=80, on=True
    )


async def test_apply_static_temperature_pushes_per_led() -> None:
    """Static Temperature pushes per-LED temperature/brightness/state lists."""
    coordinator = AsyncMock()
    pixels = [_pixel(temperature=3000), _pixel(temperature=5000, on=False)]
    ctx = ApplyContext(
        coordinator=coordinator, light=5, pixels=pixels, speed=0, random=False
    )
    await get_effect_mode(EFFECT_STATIC_TEMPERATURE).apply(ctx)
    coordinator.async_set_temperature_pixels.assert_awaited_once_with(
        5, temperatures=[3000, 5000], brightness=[80, 80], states=[True, False]
    )


async def test_apply_animated_effect_uses_lit_pixels() -> None:
    """An animated effect sends only the lit pixels, with speed/randomize/level."""
    coordinator = AsyncMock()
    pixels = [_pixel(hue=10), _pixel(hue=20, on=False), _pixel(hue=30)]
    ctx = ApplyContext(
        coordinator=coordinator, light=5, pixels=pixels, speed=4, random=True
    )
    await get_effect_mode("rainbow").apply(ctx)
    coordinator.async_set_effect_pixels.assert_awaited_once_with(
        5,
        colors=[(10, 60), (30, 60)],
        brightness=[80, 80],
        effect=ColorEffect.RAINBOW,
        speed=4,
        randomize=True,
        level=80,
    )
