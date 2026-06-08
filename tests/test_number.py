"""Tests for the InvisOutlet number platform."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.invisoutlet.const import (
    CONF_EFFECTS,
    DOMAIN,
    SUBENTRY_AURA_EFFECT,
)

from .conftest import EFFECT_ID, SERIAL, init_integration


async def test_config_number_writes_config(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Setting a config number writes it via set_config as an int."""
    await init_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id(
        "number", DOMAIN, f"{SERIAL}_pm_indicator_brightness"
    )
    assert hass.states.get(entity_id).state == "50"

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: 30},
        blocking=True,
    )
    mock_client.set_config.assert_awaited_with(pm_indicator_brightness=30)


async def test_effect_speed_number_persists(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry_with_effect: MockConfigEntry,
) -> None:
    """The per-effect Speed slider persists into the effect's subentry data."""
    entry = await init_integration(hass, mock_config_entry_with_effect)
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("number", DOMAIN, f"{EFFECT_ID}_speed")
    assert hass.states.get(entity_id).state == "3"

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: 5},
        blocking=True,
    )
    subentry = entry.get_subentries_of_type(SUBENTRY_AURA_EFFECT)[0]
    assert subentry.data[CONF_EFFECTS][EFFECT_ID]["speed"] == 5
