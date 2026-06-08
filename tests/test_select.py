"""Tests for the InvisOutlet select platform."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.invisoutlet.const import (
    CONF_EFFECTS,
    CONF_OUTLETS,
    CONF_SUB_DEVICE_UPDATE_METHOD,
    DOMAIN,
    SUBENTRY_AURA_EFFECT,
)

from .conftest import EFFECT_ID, SERIAL, init_integration


async def test_update_method_select_persists(
    hass: HomeAssistant,
    mock_client_deco: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Choosing an update-delivery method stores it in the outlet config."""
    entry = await init_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("select", DOMAIN, f"{SERIAL}_update_method")
    assert entity_id is not None
    assert hass.states.get(entity_id).state == "Wi-Fi"

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: "Via InvisOutlet"},
        blocking=True,
    )
    assert (
        entry.data[CONF_OUTLETS][SERIAL][CONF_SUB_DEVICE_UPDATE_METHOD] == 1
    )


async def test_effect_mode_select_persists(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry_with_effect: MockConfigEntry,
) -> None:
    """Changing an effect's mode persists into the effect's subentry data."""
    entry = await init_integration(hass, mock_config_entry_with_effect)
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("select", DOMAIN, f"{EFFECT_ID}_effect")
    assert hass.states.get(entity_id).state == "rainbow"

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: "breathing"},
        blocking=True,
    )
    subentry = entry.get_subentries_of_type(SUBENTRY_AURA_EFFECT)[0]
    assert subentry.data[CONF_EFFECTS][EFFECT_ID]["mode"] == "breathing"
