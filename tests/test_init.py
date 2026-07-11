"""Tests for InvisOutlet setup, unload and registry housekeeping."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr, entity_registry as er
from invisoutlet import InvisOutletConnectionError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.invisoutlet import async_remove_config_entry_device
from custom_components.invisoutlet.const import (
    CONF_ENTRY_TYPE,
    CONF_OUTLETS,
    DOMAIN,
    ENTRY_TYPE_HUB,
)

from .conftest import HOST, SERIAL, init_integration


async def test_setup_and_unload(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A hub entry loads, creates entities, and unloads cleanly."""
    entry = await init_integration(hass, mock_config_entry)
    assert entry.state is ConfigEntryState.LOADED

    ent_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    assert entities  # platforms created entities for the outlet
    # The outlet switch is present.
    assert ent_reg.async_get_entity_id("switch", DOMAIN, f"{SERIAL}_outlet_1")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    mock_client.close.assert_awaited()


async def test_setup_unreachable_outlet_is_skipped(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """An outlet that can't be reached is skipped but the entry still loads."""
    mock_client.connect.side_effect = InvisOutletConnectionError("unreachable")
    entry = await init_integration(hass, mock_config_entry)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data == {}
    ent_reg = er.async_get(hass)
    assert not er.async_entries_for_config_entry(ent_reg, entry.entry_id)


async def test_setup_creates_outlet_device(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The outlet is registered as a device under the hub entry."""
    await init_integration(hass, mock_config_entry)
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, SERIAL)})
    assert device is not None
    assert device.manufacturer == "Intecular"


async def test_chosen_name_and_area_applied_before_entities(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """The flow-chosen name/area land on the device and drive the entity ids."""
    area = ar.async_get(hass).async_create("Test Lab")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="InvisOutlet Devices",
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_HUB,
            CONF_OUTLETS: {
                SERIAL: {"host": HOST, "name": "Lab Rig", "area": area.id}
            },
        },
    )
    await init_integration(hass, entry)

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, SERIAL)})
    assert device is not None
    assert device.name_by_user == "Lab Rig"
    assert device.area_id == area.id

    # Entity ids derive from the chosen area + name (HA prefixes the area when
    # the device has one at creation), not the model + serial name the
    # entities' device_info later applies.
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("switch", DOMAIN, f"{SERIAL}_outlet_1")
    assert entity_id == "switch.test_lab_lab_rig_outlet_1"


async def test_remove_outlet_device(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Removing an outlet's device drops it from the stored outlet map."""
    entry = await init_integration(hass, mock_config_entry)
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, SERIAL)})
    assert device is not None

    allowed = await async_remove_config_entry_device(hass, entry, device)
    assert allowed is True
    assert SERIAL not in entry.data[CONF_OUTLETS]


async def test_reconcile_removes_stale_entity(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A registry entity with no backing outlet/effect is pruned on setup."""
    mock_config_entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    stale = ent_reg.async_get_or_create(
        "switch",
        DOMAIN,
        "GHOSTSERIAL_outlet_1",
        config_entry=mock_config_entry,
    )
    assert ent_reg.async_get(stale.entity_id) is not None

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert ent_reg.async_get(stale.entity_id) is None
