"""Tests for the InvisOutlet binary sensor platform."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from invisoutlet import SensorData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.invisoutlet.const import DOMAIN

from .conftest import SERIAL, init_integration, push_sensor


async def test_occupancy_and_motion(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Occupancy and motion reflect the reported sensor data."""
    await init_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)

    occ_id = ent_reg.async_get_entity_id("binary_sensor", DOMAIN, f"{SERIAL}_occupancy")
    motion_id = ent_reg.async_get_entity_id("binary_sensor", DOMAIN, f"{SERIAL}_motion")
    assert hass.states.get(occ_id).state == STATE_ON
    assert hass.states.get(motion_id).state == STATE_ON

    # A push with no movement flips motion off.
    await push_sensor(
        hass, mock_client, SensorData(occupancy_state=0, movement_energy=0)
    )
    assert hass.states.get(occ_id).state == STATE_OFF
    assert hass.states.get(motion_id).state == STATE_OFF
