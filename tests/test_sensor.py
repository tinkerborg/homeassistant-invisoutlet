"""Tests for the InvisOutlet sensor platform."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from invisoutlet import SensorData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.invisoutlet.const import DOMAIN

from .conftest import SERIAL, init_integration, push_sensor


async def test_environmental_sensors(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Reported readings surface as sensor states."""
    await init_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)

    temp_id = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_temperature")
    assert hass.states.get(temp_id).state == "21.5"
    co2_id = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_co2")
    assert hass.states.get(co2_id).state == "600"


async def test_status_sensor_ok(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """With a healthy outlet and no faceplate the status reads OK."""
    await init_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)
    status_id = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_status")
    assert hass.states.get(status_id).state == "OK"


async def test_status_sensor_waits_for_faceplate(
    hass: HomeAssistant,
    mock_client_deco: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """With a faceplate attached but not yet streaming, status is 'Waiting'."""
    await init_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)
    status_id = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_status")
    assert hass.states.get(status_id).state.startswith("Waiting")

    # Once it streams, it flips to OK.
    await push_sensor(hass, mock_client_deco, SensorData(temperature=20.0))
    assert hass.states.get(status_id).state == "OK"


async def test_sensor_updates_on_push(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A pushed reading updates the sensor state."""
    await init_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)
    temp_id = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_temperature")

    await push_sensor(hass, mock_client, SensorData(temperature=25.5, humidity=40.0))
    assert hass.states.get(temp_id).state == "25.5"


async def test_diagnostic_sensors_are_disabled_by_default(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Connection-health sensors are registered but off until asked for."""
    await init_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)

    for key in (
        "transport",
        "reconnects",
        "faceplate_dropouts",
        "connected_since",
        "last_sensor_push",
    ):
        entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_{key}")
        assert entity_id is not None, key
        assert ent_reg.async_get(entity_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(entity_id) is None


async def test_connection_counters_track_drops(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A drop counts a reconnect; a quiet faceplate counts a dropout."""
    entry = await init_integration(hass, mock_config_entry)
    coordinator = entry.runtime_data[SERIAL]
    assert coordinator.reconnects == 0
    assert coordinator.faceplate_dropouts == 0

    coordinator._handle_disconnect()
    assert coordinator.reconnects == 1
    assert coordinator.connected_since is None

    await push_sensor(hass, mock_client, SensorData(temperature=20.0))
    assert coordinator.last_sensor_push is not None
    coordinator._cancel_sub_device_watchdog()
    coordinator._sub_device_timed_out(None)
    assert coordinator.faceplate_dropouts == 1
