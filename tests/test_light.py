"""Tests for the InvisOutlet light platform."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    DOMAIN as LIGHT_DOMAIN,
)
from invisoutlet.client import CALLBACK_COLOR_LIGHT
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
)
from homeassistant.config_entries import ConfigSubentryData
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from invisoutlet import InvisOutletError, SensorData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.invisoutlet.const import (
    CONF_COLOR_EFFECTS,
    CONF_EFFECTS,
    CONF_ENTRY_TYPE,
    CONF_OUTLETS,
    DOMAIN,
    ENTRY_TYPE_HUB,
    SUBENTRY_AURA_EFFECT,
)

from .conftest import (
    EFFECT_ID,
    HOST,
    SERIAL,
    init_integration,
    message_handler,
    push_sensor,
)


def _color_frame(hue: int = 200, sat: int = 60, mode: int = 1, state: int = 1) -> dict:
    """A callback-18 color-array push envelope with one LED (mode 1 = static)."""
    return {
        "payload": {"callbackArgs": [5, mode, [[state, 80, [hue, sat], 4000]]]},
    }


# "Sunset" is a rainbow effect (device mode 6); its echo must report that mode
# and its lit-pixel color (200, 60) or the reconciliation would drop it.
_RAINBOW_ECHO = _color_frame(hue=200, sat=60, mode=6)


async def test_nightlight_turn_on_off(
    hass: HomeAssistant,
    mock_client_deco: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The faceplate nightlight controls set_nightlight once the faceplate is up."""
    await init_integration(hass, mock_config_entry)
    await push_sensor(hass, mock_client_deco, SensorData(temperature=20.0))
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("light", DOMAIN, f"{SERIAL}_nightlight")
    assert entity_id is not None
    assert hass.states.get(entity_id).state == STATE_ON

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id, ATTR_BRIGHTNESS: 128},
        blocking=True,
    )
    assert mock_client_deco.set_nightlight.await_args.args[0] == 1

    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert mock_client_deco.set_nightlight.await_args.args[0] == 0


async def test_aura_color_light_set_hs(
    hass: HomeAssistant,
    mock_client_aura: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An Aura faceplate exposes a color light that sets an HSV color."""
    await init_integration(hass, mock_config_entry)
    await push_sensor(hass, mock_client_aura, SensorData(temperature=20.0))
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("light", DOMAIN, f"{SERIAL}_colorlight")
    assert entity_id is not None

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id, ATTR_HS_COLOR: (200, 50)},
        blocking=True,
    )
    mock_client_aura.set_color_hsv.assert_awaited()


async def test_effect_virtual_pixel_persists(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry_with_effect: MockConfigEntry,
) -> None:
    """A virtual effect pixel stores its color into the effect's subentry data."""
    entry = await init_integration(hass, mock_config_entry_with_effect)
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("light", DOMAIN, f"{EFFECT_ID}_pixel_0")
    assert entity_id is not None
    assert hass.states.get(entity_id).state == STATE_ON

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id, ATTR_HS_COLOR: (120, 80), ATTR_BRIGHTNESS: 200},
        blocking=True,
    )
    subentry = entry.get_subentries_of_type(SUBENTRY_AURA_EFFECT)[0]
    pixel = subentry.data[CONF_EFFECTS][EFFECT_ID]["pixel_0"]
    assert pixel["on"] is True
    assert list(pixel["hs"]) == [120, 80]


async def test_color_light_effect_list_sorted_by_name(
    hass: HomeAssistant, mock_client_aura: AsyncMock
) -> None:
    """The Color Light's effect dropdown is alphabetical, not insertion order."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="InvisOutlet Devices",
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_HUB,
            CONF_OUTLETS: {SERIAL: {"host": HOST}},
        },
        subentries_data=[
            ConfigSubentryData(
                data={
                    CONF_EFFECTS: {
                        "e1": {"name": "Zebra"},
                        "e2": {"name": "apple"},
                        "e3": {"name": "Mango"},
                    }
                },
                subentry_type=SUBENTRY_AURA_EFFECT,
                title="InvisOutlet Aura Effects",
                unique_id=None,
            )
        ],
    )
    await init_integration(hass, entry)
    await push_sensor(hass, mock_client_aura, SensorData(temperature=20.0))
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("light", DOMAIN, f"{SERIAL}_colorlight")

    effect_list = hass.states.get(entity_id).attributes["effect_list"]
    # "Static" always leads; the rest are case-insensitively alphabetical.
    assert effect_list == ["Static", "apple", "Mango", "Zebra"]


async def test_color_light_reflects_pushed_state(
    hass: HomeAssistant,
    mock_client_aura: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A pushed color-array frame surfaces as on/brightness/color."""
    await init_integration(hass, mock_config_entry)
    await push_sensor(hass, mock_client_aura, SensorData(temperature=20.0))
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("light", DOMAIN, f"{SERIAL}_colorlight")

    message_handler(mock_client_aura, CALLBACK_COLOR_LIGHT)(_color_frame(hue=120, sat=90))
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == STATE_ON
    assert state.attributes["hs_color"] == (120, 90)
    assert "colors" in state.attributes  # per-LED RGB palette


async def test_color_light_set_color_temp(
    hass: HomeAssistant,
    mock_client_aura: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Setting a white temperature calls set_color_temperature."""
    await init_integration(hass, mock_config_entry)
    await push_sensor(hass, mock_client_aura, SensorData(temperature=20.0))
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("light", DOMAIN, f"{SERIAL}_colorlight")

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id, ATTR_COLOR_TEMP_KELVIN: 3000},
        blocking=True,
    )
    mock_client_aura.set_color_temperature.assert_awaited()


async def test_color_light_turn_off(
    hass: HomeAssistant,
    mock_client_aura: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Turning the array off writes an off HSV frame."""
    await init_integration(hass, mock_config_entry)
    await push_sensor(hass, mock_client_aura, SensorData(temperature=20.0))
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("light", DOMAIN, f"{SERIAL}_colorlight")

    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    # coordinator.async_set_color_hsv forwards on/off as the 5th positional arg.
    assert mock_client_aura.set_color_hsv.await_args.args[4] is False


async def test_color_light_applies_effect_template(
    hass: HomeAssistant,
    mock_client_aura: AsyncMock,
    mock_config_entry_with_effect: MockConfigEntry,
) -> None:
    """Selecting a defined effect pushes that template to the physical array."""
    await init_integration(hass, mock_config_entry_with_effect)
    await push_sensor(hass, mock_client_aura, SensorData(temperature=20.0))
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("light", DOMAIN, f"{SERIAL}_colorlight")

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id, ATTR_EFFECT: "Sunset"},
        blocking=True,
    )
    # "Sunset" is a rainbow effect, so the animated per-pixel payload is sent.
    mock_client_aura.set_color_effect_pixels.assert_awaited()

    # The array echoes the effect's mode/color; the selected effect is exposed.
    message_handler(mock_client_aura, CALLBACK_COLOR_LIGHT)(_RAINBOW_ECHO)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["effect"] == "Sunset"

    # Selecting "Static" reverts the array to its own color (no template).
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id, ATTR_EFFECT: "Static"},
        blocking=True,
    )
    mock_client_aura.set_color_hsv.assert_awaited()
    # The array echoes the resulting static frame (mode 1).
    message_handler(mock_client_aura, CALLBACK_COLOR_LIGHT)(_color_frame(mode=1))
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["effect"] == "Static"


async def test_nightlight_error_raises(
    hass: HomeAssistant,
    mock_client_deco: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A device error while setting the nightlight surfaces to the user."""
    await init_integration(hass, mock_config_entry)
    await push_sensor(hass, mock_client_deco, SensorData(temperature=20.0))
    mock_client_deco.set_nightlight.side_effect = InvisOutletError("boom")
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("light", DOMAIN, f"{SERIAL}_nightlight")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )


async def test_effect_pixel_turn_off(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry_with_effect: MockConfigEntry,
) -> None:
    """A non-forced pixel persists off; a forced pixel bounces back on."""
    entry = await init_integration(hass, mock_config_entry_with_effect)
    ent_reg = er.async_get(hass)

    # rainbow forces only pixel 0 on, so pixel 1 can be turned off.
    free_pixel = ent_reg.async_get_entity_id("light", DOMAIN, f"{EFFECT_ID}_pixel_1")
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: free_pixel}, blocking=True
    )
    subentry = entry.get_subentries_of_type(SUBENTRY_AURA_EFFECT)[0]
    assert subentry.data[CONF_EFFECTS][EFFECT_ID]["pixel_1"]["on"] is False

    # pixel 0 is forced on, so turning it off is refused (stays on).
    forced_pixel = ent_reg.async_get_entity_id("light", DOMAIN, f"{EFFECT_ID}_pixel_0")
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: forced_pixel}, blocking=True
    )
    assert hass.states.get(forced_pixel).state == STATE_ON


# --- Color Light + effect interaction ------------------------------------


async def _color_light_with_effect(
    hass: HomeAssistant,
    mock_client_aura: AsyncMock,
    entry: MockConfigEntry,
    *,
    select: str | None = "Sunset",
) -> str:
    """Set up an online Aura color light, optionally with an effect selected."""
    await init_integration(hass, entry)
    await push_sensor(hass, mock_client_aura, SensorData(temperature=20.0))
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("light", DOMAIN, f"{SERIAL}_colorlight")
    if select is not None:
        await hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: entity_id, ATTR_EFFECT: select},
            blocking=True,
        )
        message_handler(mock_client_aura, CALLBACK_COLOR_LIGHT)(_RAINBOW_ECHO)
        await hass.async_block_till_done()
    return entity_id


async def test_color_light_effect_is_brightness_only(
    hass: HomeAssistant,
    mock_client_aura: AsyncMock,
    mock_config_entry_with_effect: MockConfigEntry,
) -> None:
    """With an effect selected, the light exposes only on/off + brightness."""
    entity_id = await _color_light_with_effect(
        hass, mock_client_aura, mock_config_entry_with_effect
    )
    state = hass.states.get(entity_id)
    assert state.attributes["supported_color_modes"] == ["brightness"]
    assert state.attributes["color_mode"] == "brightness"
    assert "hs_color" not in state.attributes or state.attributes["hs_color"] is None


async def test_color_light_brightness_scales_effect_and_persists(
    hass: HomeAssistant,
    mock_client_aura: AsyncMock,
    mock_config_entry_with_effect: MockConfigEntry,
) -> None:
    """Brightness while an effect runs rescales the animation and persists."""
    entry = mock_config_entry_with_effect
    entity_id = await _color_light_with_effect(hass, mock_client_aura, entry)
    before = mock_client_aura.set_color_effect_pixels.await_count

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id, ATTR_BRIGHTNESS: 128},
        blocking=True,
    )
    # The effect is re-applied (rescaled), not replaced by a static color.
    assert mock_client_aura.set_color_effect_pixels.await_count > before
    mock_client_aura.set_color_hsv.assert_not_awaited()

    record = entry.data[CONF_OUTLETS][SERIAL][CONF_COLOR_EFFECTS]["5"]
    assert record["effect"] == EFFECT_ID
    assert record["master"] == 128


async def test_color_light_off_on_keeps_effect_running(
    hass: HomeAssistant,
    mock_client_aura: AsyncMock,
    mock_config_entry_with_effect: MockConfigEntry,
) -> None:
    """Turning off then on resumes the effect rather than freezing a color."""
    entity_id = await _color_light_with_effect(
        hass, mock_client_aura, mock_config_entry_with_effect
    )
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    before = mock_client_aura.set_color_effect_pixels.await_count
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    # Resumed the animation; the effect stayed selected the whole time.
    assert mock_client_aura.set_color_effect_pixels.await_count > before
    message_handler(mock_client_aura, CALLBACK_COLOR_LIGHT)(_RAINBOW_ECHO)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["effect"] == "Sunset"


async def test_color_light_none_restores_base_color(
    hass: HomeAssistant,
    mock_client_aura: AsyncMock,
    mock_config_entry_with_effect: MockConfigEntry,
) -> None:
    """Selecting None restores the color that was set before the effect."""
    entity_id = await _color_light_with_effect(
        hass, mock_client_aura, mock_config_entry_with_effect, select=None
    )
    # Set a manual color first (no effect), which becomes the base.
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id, ATTR_HS_COLOR: (120, 80)},
        blocking=True,
    )
    # Now select the effect, then clear it back to Static.
    for effect in ("Sunset", "Static"):
        await hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: entity_id, ATTR_EFFECT: effect},
            blocking=True,
        )
    # The last write restores the base color (120, 80), not the effect's pixel.
    args = mock_client_aura.set_color_hsv.await_args.args
    assert args[1] == 120
    assert args[2] == 80


async def test_color_light_external_animated_effect(
    hass: HomeAssistant,
    mock_client_aura: AsyncMock,
    mock_config_entry_with_effect: MockConfigEntry,
) -> None:
    """An unmatched animated mode shows the effect type as "(External)"."""
    entity_id = await _color_light_with_effect(
        hass, mock_client_aura, mock_config_entry_with_effect
    )
    # The device is driven to a different animated effect (mode 5 = color cycle).
    message_handler(mock_client_aura, CALLBACK_COLOR_LIGHT)(_color_frame(mode=5))
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.attributes["effect"] == "Color Cycle (External)"
    assert "Color Cycle (External)" in state.attributes["effect_list"]
    # Still effect-shaped: brightness only, no color picker.
    assert state.attributes["supported_color_modes"] == ["brightness"]


async def test_color_light_external_color_diff_same_mode(
    hass: HomeAssistant,
    mock_client_aura: AsyncMock,
    mock_config_entry_with_effect: MockConfigEntry,
) -> None:
    """Same mode but different colors than our template is still external."""
    entity_id = await _color_light_with_effect(
        hass, mock_client_aura, mock_config_entry_with_effect
    )
    # Rainbow mode (6) but a color we never set — an app recolor.
    message_handler(mock_client_aura, CALLBACK_COLOR_LIGHT)(
        _color_frame(hue=100, sat=50, mode=6)
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["effect"] == "Rainbow (External)"


async def test_color_light_external_static_adopts_static(
    hass: HomeAssistant,
    mock_client_aura: AsyncMock,
    mock_config_entry_with_effect: MockConfigEntry,
) -> None:
    """An external *static* change is renderable, so we drop to "Static"."""
    entity_id = await _color_light_with_effect(
        hass, mock_client_aura, mock_config_entry_with_effect
    )
    # The app sets a plain static color (mode 1) while on.
    message_handler(mock_client_aura, CALLBACK_COLOR_LIGHT)(
        _color_frame(hue=30, sat=90, mode=1)
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.attributes["effect"] == "Static"
    # The selection was cleared, so full color control is back.
    assert set(state.attributes["supported_color_modes"]) == {"hs", "color_temp"}


async def test_color_light_resume_from_external(
    hass: HomeAssistant,
    mock_client_aura: AsyncMock,
    mock_config_entry_with_effect: MockConfigEntry,
) -> None:
    """Picking an effect while external reasserts control (pushes the template)."""
    entity_id = await _color_light_with_effect(
        hass, mock_client_aura, mock_config_entry_with_effect
    )
    message_handler(mock_client_aura, CALLBACK_COLOR_LIGHT)(_color_frame(mode=5))
    await hass.async_block_till_done()
    before = mock_client_aura.set_color_effect_pixels.await_count

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id, ATTR_EFFECT: "Sunset"},
        blocking=True,
    )
    assert mock_client_aura.set_color_effect_pixels.await_count > before


async def test_color_light_static_temperature_restores(
    hass: HomeAssistant,
    mock_client_aura: AsyncMock,
    mock_config_entry_with_effect: MockConfigEntry,
) -> None:
    """Static remembers a temperature and restores it after an effect."""
    entity_id = await _color_light_with_effect(
        hass, mock_client_aura, mock_config_entry_with_effect, select=None
    )
    # Set a white temperature as the static base.
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id, ATTR_COLOR_TEMP_KELVIN: 3000},
        blocking=True,
    )
    # Select an effect, then go back to Static.
    for effect in ("Sunset", "Static"):
        await hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: entity_id, ATTR_EFFECT: effect},
            blocking=True,
        )
    # Static restored the temperature (not an HSV color).
    assert mock_client_aura.set_color_temperature.await_args.args[1] == 3000


async def test_faceplate_swap_prunes_stale_light(
    hass: HomeAssistant,
    mock_client_aura: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Swapping faceplates removes the previous faceplate's light entity."""
    mock_config_entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    # A Nightlight left over from a previous InvisDeco faceplate.
    stale = ent_reg.async_get_or_create(
        "light", DOMAIN, f"{SERIAL}_nightlight", config_entry=mock_config_entry
    )

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # The Aura faceplate creates the Color Light and the stale Nightlight is gone.
    assert ent_reg.async_get_entity_id("light", DOMAIN, f"{SERIAL}_colorlight")
    assert ent_reg.async_get(stale.entity_id) is None
