"""Tests for the InvisOutlet update platform."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.update import (
    DOMAIN as UPDATE_DOMAIN,
    SERVICE_INSTALL,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from invisoutlet import InvisOutletError, OtaProgress, OtaResult
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.invisoutlet.const import DOMAIN

from .conftest import (
    SERIAL,
    init_integration,
    make_device_info,
    registered_callback,
)


async def _start_install(hass: HomeAssistant, entity_id: str, mock_client: AsyncMock):
    """Start the install service and park it awaiting the terminal result."""
    call = hass.async_create_task(
        hass.services.async_call(
            UPDATE_DOMAIN, SERVICE_INSTALL, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )
    )
    for _ in range(10):
        await asyncio.sleep(0)
    return call


async def test_update_entities_report_versions(
    hass: HomeAssistant,
    mock_client_deco: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The deco update entity shows an available newer firmware."""
    await init_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("update", DOMAIN, f"{SERIAL}_update_invisdeco")
    assert entity_id is not None

    state = hass.states.get(entity_id)
    assert state.state == STATE_ON  # update available
    assert state.attributes["installed_version"] == "3.0"
    assert state.attributes["latest_version"] == "3.1"


async def test_update_progress_push(
    hass: HomeAssistant,
    mock_client_deco: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A pushed OTA progress event surfaces as in-progress with a percentage."""
    await init_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("update", DOMAIN, f"{SERIAL}_update_invisdeco")

    registered_callback(mock_client_deco, "on_ota_progress")(
        OtaProgress(device_type=2, progress=42)
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.attributes["in_progress"] is True
    assert state.attributes["update_percentage"] == 42


async def test_update_install_failure_raises(
    hass: HomeAssistant,
    mock_client_deco: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Install starts the OTA and raises when the terminal result is a failure."""
    await init_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("update", DOMAIN, f"{SERIAL}_update_invisdeco")

    call = hass.async_create_task(
        hass.services.async_call(
            UPDATE_DOMAIN, SERVICE_INSTALL, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )
    )
    # Yield (without block_till_done, which would wait on the parked install) so
    # the install starts the OTA and reaches its await on the result future.
    for _ in range(10):
        await asyncio.sleep(0)
    mock_client_deco.perform_ota_update.assert_awaited()

    # The gated result comes back a failure; the install must raise.
    registered_callback(mock_client_deco, "on_ota_result")(
        OtaResult(device_type=2, status=0)
    )
    with pytest.raises(HomeAssistantError):
        await asyncio.wait_for(call, timeout=5)


async def test_update_install_success_clears_when_version_moves(
    hass: HomeAssistant,
    mock_client_deco: AsyncMock,
    mock_config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful install holds until the module reports its new version."""
    monkeypatch.setattr(
        "custom_components.invisoutlet.coordinator._POST_UPDATE_REFRESH_DELAYS", (0,)
    )
    await init_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("update", DOMAIN, f"{SERIAL}_update_invisdeco")

    call = await _start_install(hass, entity_id, mock_client_deco)
    mock_client_deco.perform_ota_update.assert_awaited()

    # After the reboot the deco reports a new firmware revision.
    updated = make_device_info(with_deco=True)
    updated.sub_device.fw_rev = "3.1"
    mock_client_deco.get_device_info.return_value = updated

    registered_callback(mock_client_deco, "on_ota_result")(
        OtaResult(device_type=2, status=1)
    )
    await asyncio.wait_for(call, timeout=5)
    await hass.async_block_till_done()

    # The in-progress state has cleared and the new version is installed.
    coordinator = mock_config_entry.runtime_data[SERIAL]
    assert coordinator.ota_progress == {}
    assert hass.states.get(entity_id).attributes["installed_version"] == "3.1"


async def test_update_install_start_failure_raises(
    hass: HomeAssistant,
    mock_client_deco: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A failure to even start the OTA raises immediately."""
    mock_client_deco.perform_ota_update.side_effect = InvisOutletError("nope")
    await init_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("update", DOMAIN, f"{SERIAL}_update_invisdeco")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            UPDATE_DOMAIN, SERVICE_INSTALL, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )
