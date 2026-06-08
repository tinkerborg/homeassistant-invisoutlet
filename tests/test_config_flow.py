"""Tests for the InvisOutlet config flow."""

from __future__ import annotations

from ipaddress import ip_address
from unittest.mock import AsyncMock

from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from invisoutlet import InvisOutletConnectionError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.invisoutlet.const import (
    CONF_EFFECTS,
    CONF_ENTRY_TYPE,
    CONF_OUTLETS,
    DOMAIN,
    ENTRY_TYPE_HUB,
    SUBENTRY_AURA_EFFECT,
)

from .conftest import HOST, SERIAL


def _zeroconf_info(
    *, serial: str | None = SERIAL, host: str = HOST, model: str = "InvisOutlet"
) -> ZeroconfServiceInfo:
    """Build a zeroconf discovery payload as the device advertises it."""
    properties: dict[str, str] = {}
    if serial is not None:
        properties["sn"] = serial
    if model:
        properties["device"] = model
    return ZeroconfServiceInfo(
        ip_address=ip_address(host),
        ip_addresses=[ip_address(host)],
        port=80,
        hostname=f"{serial}.local.",
        type="_invis._tcp.local.",
        name=f"{serial}._invis._tcp.local.",
        properties=properties,
    )


async def test_user_flow_creates_hub(
    hass: HomeAssistant, mock_client: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """A manual add probes the outlet and creates the hub entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "outlet"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "InvisOutlet Devices"
    assert result["data"] == {
        CONF_ENTRY_TYPE: ENTRY_TYPE_HUB,
        CONF_OUTLETS: {SERIAL: {CONF_HOST: HOST}},
    }


async def test_user_flow_cannot_connect_then_recovers(
    hass: HomeAssistant, mock_client: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """An unreachable outlet shows an error, then succeeds on retry."""
    mock_client.connect.side_effect = InvisOutletConnectionError("boom")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_client.connect.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_adds_outlet_to_existing_hub(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_setup_entry: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A second outlet is appended to the existing hub, not a new entry."""
    mock_config_entry.add_to_hass(hass)
    mock_client.get_device_info.return_value.serial_number = "SN_SECOND"

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "10.0.0.50"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "outlet_added"
    assert set(mock_config_entry.data[CONF_OUTLETS]) == {SERIAL, "SN_SECOND"}


async def test_user_flow_duplicate_outlet_aborts(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_setup_entry: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Re-adding an already-configured outlet aborts."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_zeroconf_discovery_creates_hub(
    hass: HomeAssistant, mock_client: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """A discovered outlet is confirmed and creates the hub."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf_info()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_OUTLETS] == {SERIAL: {CONF_HOST: HOST}}


async def test_zeroconf_without_serial_aborts(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """A discovery missing the serial number is rejected."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf_info(serial=None)
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_serial"


async def test_zeroconf_known_outlet_updates_host(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Re-discovering a known outlet at a new IP refreshes its host and aborts."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_ZEROCONF},
        data=_zeroconf_info(host="10.0.0.250"),
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_OUTLETS][SERIAL][CONF_HOST] == "10.0.0.250"


async def test_aura_effect_subentry_flow_appends(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_setup_entry: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Adding an Aura effect creates the shared subentry, then appends to it."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_AURA_EFFECT),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Sunset"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "added"
    await hass.async_block_till_done()

    subentries = mock_config_entry.get_subentries_of_type(SUBENTRY_AURA_EFFECT)
    assert len(subentries) == 1
    effects = subentries[0].data[CONF_EFFECTS]
    assert [e["name"] for e in effects.values()] == ["Sunset"]

    # A second add appends into the same subentry rather than making a new one.
    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_AURA_EFFECT),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Aurora"}
    )
    await hass.async_block_till_done()

    subentries = mock_config_entry.get_subentries_of_type(SUBENTRY_AURA_EFFECT)
    assert len(subentries) == 1
    names = {e["name"] for e in subentries[0].data[CONF_EFFECTS].values()}
    assert names == {"Sunset", "Aurora"}
