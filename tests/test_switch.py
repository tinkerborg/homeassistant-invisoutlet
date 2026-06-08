"""Tests for the InvisOutlet switch platform."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.invisoutlet.const import (
    CONF_EFFECTS,
    DOMAIN,
    SUBENTRY_AURA_EFFECT,
)

from .conftest import EFFECT_ID, SERIAL, init_integration


async def test_outlet_switch_turns_off(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The outlet switch reflects state and sends set_outlet on toggle."""
    await init_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("switch", DOMAIN, f"{SERIAL}_outlet_1")
    assert entity_id is not None
    assert hass.states.get(entity_id).state == STATE_ON

    await hass.services.async_call(
        "switch", SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_client.set_outlet.assert_awaited_with(1, False)


async def test_config_switch_writes_config(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A config switch writes the setting via set_config."""
    await init_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("switch", DOMAIN, f"{SERIAL}_capacitive_ctrl")
    assert entity_id is not None
    assert hass.states.get(entity_id).state == STATE_ON

    await hass.services.async_call(
        "switch", SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_client.set_config.assert_awaited_with(capacitive_ctrl=False)


async def test_effect_random_switch_persists(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry_with_effect: MockConfigEntry,
) -> None:
    """The per-effect Random toggle persists into the effect's subentry data."""
    entry = await init_integration(hass, mock_config_entry_with_effect)
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("switch", DOMAIN, f"{EFFECT_ID}_random")
    assert entity_id is not None
    assert hass.states.get(entity_id).state == STATE_OFF

    await hass.services.async_call(
        "switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    subentry = entry.get_subentries_of_type(SUBENTRY_AURA_EFFECT)[0]
    assert subentry.data[CONF_EFFECTS][EFFECT_ID]["random"] is True
