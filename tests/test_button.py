"""Tests for the InvisOutlet button platform."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from invisoutlet import SensorData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.invisoutlet.const import DOMAIN

from .conftest import SERIAL, init_integration, push_sensor


async def test_restart_outlet_button(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Pressing the outlet restart button calls restart."""
    await init_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("button", DOMAIN, f"{SERIAL}_restart_outlet")
    assert entity_id is not None

    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_client.restart.assert_awaited_once()


async def test_restart_deco_button_requires_online(
    hass: HomeAssistant,
    mock_client_deco: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The deco restart button appears with a faceplate and restarts it once online."""
    await init_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id(
        "button", DOMAIN, f"{SERIAL}_restart_invisdeco"
    )
    assert entity_id is not None

    # Bring the faceplate online so the button is available, then press.
    await push_sensor(hass, mock_client_deco, SensorData(temperature=20.0))
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_client_deco.restart_invisdeco.assert_awaited_once()
