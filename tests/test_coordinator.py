"""Tests for the InvisOutlet coordinator behavior (event-driven state)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from unittest.mock import patch

from invisoutlet import InvisOutletError, OtaProgress, OtaResult, OutletStatus
from invisoutlet.client import CALLBACK_DEVICE_INFO, CALLBACK_NIGHTLIGHT_STATUS
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.invisoutlet.const import DOMAIN

from .conftest import (
    SERIAL,
    init_integration,
    make_device_info,
    message_handler,
    push_outlets,
    push_sensor,
    registered_callback,
)
from invisoutlet import SensorData


def _outlet_entity(hass: HomeAssistant) -> str:
    return er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{SERIAL}_outlet_1")


def _status_entity(hass: HomeAssistant) -> str:
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_status")


async def test_outlet_push_updates_state(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A pushed outlet status updates the switch without a poll."""
    await init_integration(hass, mock_config_entry)
    entity_id = _outlet_entity(hass)
    assert hass.states.get(entity_id).state == STATE_ON

    await push_outlets(hass, mock_client, OutletStatus(outlets=[False, True]))
    assert hass.states.get(entity_id).state == STATE_OFF


async def test_disconnect_marks_unavailable(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A dropped connection marks the outlet entities unavailable."""
    await init_integration(hass, mock_config_entry)
    entity_id = _outlet_entity(hass)

    registered_callback(mock_client, "on_disconnect")()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE


async def test_reconnect_resyncs_device(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A reconnect re-reads device info and config (pushes were missed)."""
    await init_integration(hass, mock_config_entry)
    before = mock_client.get_device_info.call_count

    registered_callback(mock_client, "on_connect")()
    await hass.async_block_till_done()
    assert mock_client.get_device_info.call_count > before
    assert hass.states.get(_outlet_entity(hass)).state in (STATE_ON, STATE_OFF)


async def test_setup_survives_read_failures(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Failing initial sensor/nightlight/color reads don't block setup."""
    mock_client.get_sensor_data.side_effect = InvisOutletError("no sensors")
    mock_client.get_nightlight.side_effect = InvisOutletError("no nightlight")
    mock_client.get_color.side_effect = InvisOutletError("no aura")

    entry = await init_integration(hass, mock_config_entry)
    from homeassistant.config_entries import ConfigEntryState

    assert entry.state is ConfigEntryState.LOADED


async def test_update_failed_marks_unavailable(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A failed refresh (reconnect re-pull) surfaces as unavailable."""
    await init_integration(hass, mock_config_entry)
    mock_client.get_outlet_status.side_effect = InvisOutletError("down")

    registered_callback(mock_client, "on_connect")()
    await hass.async_block_till_done()
    assert hass.states.get(_outlet_entity(hass)).state == STATE_UNAVAILABLE


async def test_nightlight_push_updates_state(
    hass: HomeAssistant,
    mock_client_deco: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A callback-15 nightlight push updates the coordinator's nightlight."""
    await init_integration(hass, mock_config_entry)
    await push_sensor(hass, mock_client_deco, SensorData(temperature=20.0))
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("light", DOMAIN, f"{SERIAL}_nightlight")

    message_handler(mock_client_deco, CALLBACK_NIGHTLIGHT_STATUS)(
        {"payload": {"callbackArgs": [0, 0]}}
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_OFF


async def test_ota_pushes_ignore_unknown_target(
    hass: HomeAssistant,
    mock_client_deco: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """OTA progress/result for an unrecognized device type are ignored."""
    await init_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data[SERIAL]

    registered_callback(mock_client_deco, "on_ota_progress")(
        OtaProgress(device_type=99, progress=10)
    )
    registered_callback(mock_client_deco, "on_ota_result")(
        OtaResult(device_type=99, status=1)
    )
    await hass.async_block_till_done()
    assert coordinator.ota_progress == {}


async def test_sub_device_watchdog_marks_offline(
    hass: HomeAssistant,
    mock_client_deco: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """No faceplate pushes within the window flips it back offline."""
    await init_integration(hass, mock_config_entry)
    await push_sensor(hass, mock_client_deco, SensorData(temperature=20.0))
    assert hass.states.get(_status_entity(hass)).state == "OK"

    freezer.tick(timedelta(seconds=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(_status_entity(hass)).state.startswith("Waiting")


async def test_device_info_push_resyncs(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A device-info push (device restarted) re-reads config."""
    await init_integration(hass, mock_config_entry)
    before = mock_client.get_config.call_count

    message_handler(mock_client, CALLBACK_DEVICE_INFO)({"payload": {"callbackArgs": {}}})
    await hass.async_block_till_done()
    assert mock_client.get_config.call_count > before


async def test_resync_tolerates_config_error(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A config read failing during resync is swallowed."""
    await init_integration(hass, mock_config_entry)
    mock_client.get_config.side_effect = InvisOutletError("no config")

    registered_callback(mock_client, "on_connect")()
    await hass.async_block_till_done()  # must not raise


async def test_firmware_check_tolerates_error(
    hass: HomeAssistant,
    mock_client_deco: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A failing firmware lookup doesn't break the resync."""
    await init_integration(hass, mock_config_entry)
    mock_client_deco.check_firmware.side_effect = InvisOutletError("service down")

    registered_callback(mock_client_deco, "on_connect")()
    await hass.async_block_till_done()  # must not raise


async def test_faceplate_swap_schedules_reload(
    hass: HomeAssistant,
    mock_client_deco: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A different faceplate serial on reconnect triggers a full reload."""
    entry = await init_integration(hass, mock_config_entry)

    swapped = make_device_info(with_deco=True)
    swapped.sub_device.serial_number = "DIFFERENT"
    mock_client_deco.get_device_info.return_value = swapped

    with patch.object(
        hass.config_entries, "async_schedule_reload"
    ) as reload:
        registered_callback(mock_client_deco, "on_connect")()
        await hass.async_block_till_done()

    reload.assert_called_with(entry.entry_id)
