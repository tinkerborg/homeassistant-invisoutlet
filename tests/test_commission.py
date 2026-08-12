"""Tests for the Matter-commissioning interceptor and flow path."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.websocket_api import const as ws_const
from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    SOURCE_USER,
    ConfigEntryChange,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.invisoutlet.commission import (
    COMMISSION_COMMAND,
    EVENT_COMMISSION_FINISHED,
    EVENT_COMMISSIONED,
    FINISHED_COMMAND,
    async_find_commissionable_ip,
    async_identify_commission,
    async_ip_advertises_invis,
    parse_setup_code,
)
from custom_components.invisoutlet.const import CONF_OUTLETS, DOMAIN
from custom_components.invisoutlet.ws_intercept import (
    async_delegate,
    async_intercept_command,
)

from .conftest import init_integration

_BASE38 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-."


def _base38_encode(data: bytes) -> str:
    """Inverse of the decoder under test (3 bytes -> 5 chars, little-endian)."""
    out = ""
    for i in range(0, len(data), 3):
        chunk = data[i : i + 3]
        value = int.from_bytes(chunk, "little")
        for _ in range({3: 5, 2: 4, 1: 2}[len(chunk)]):
            out += _BASE38[value % 38]
            value //= 38
    return out


def _make_code(
    *,
    version: int = 0,
    vendor_id: int = 0xFFF1,
    product_id: int = 0x8001,
    commissioning_flow: int = 0,
    discovery_capabilities: int = 4,
    discriminator: int = 3840,
    passcode: int = 20202021,
) -> str:
    """Build a Matter QR setup code from known field values."""
    value = (
        (version & 0x7)
        | ((vendor_id & 0xFFFF) << 3)
        | ((product_id & 0xFFFF) << 19)
        | ((commissioning_flow & 0x3) << 35)
        | ((discovery_capabilities & 0xFF) << 37)
        | ((discriminator & 0xFFF) << 45)
        | ((passcode & 0x7FFFFFF) << 57)
    )
    return "MT:" + _base38_encode(value.to_bytes(11, "little"))


def test_parse_setup_code_round_trip() -> None:
    """A code built from known fields decodes back to those fields."""
    code = _make_code(
        vendor_id=5226, product_id=32769, discriminator=899, passcode=82500218
    )
    payload = parse_setup_code(code)
    assert payload.vendor_id == 5226
    assert payload.product_id == 32769
    assert payload.discriminator == 899
    assert payload.passcode == 82500218
    assert payload.discovery_capabilities == 4


def test_parse_setup_code_rejects_non_matter() -> None:
    """A non-Matter string is rejected."""
    with pytest.raises(ValueError, match="not a Matter QR setup code"):
        parse_setup_code("https://example.com")


def test_parse_setup_code_too_short() -> None:
    """A code that decodes to fewer than 11 bytes is rejected."""
    with pytest.raises(ValueError, match="too short"):
        parse_setup_code("MT:00")


async def test_identify_commission_ours(hass: HomeAssistant) -> None:
    """A code that resolves to an IP advertising _invis is flagged as ours."""
    code = _make_code(discriminator=1234)
    with (
        patch(
            "custom_components.invisoutlet.commission.async_find_commissionable_ip",
            AsyncMock(return_value="10.0.0.77"),
        ),
        patch(
            "custom_components.invisoutlet.commission.async_ip_advertises_invis",
            AsyncMock(return_value=True),
        ),
    ):
        detail = await async_identify_commission(hass, code)
    assert detail["is_invisoutlet"] is True
    assert detail["ip"] == "10.0.0.77"
    assert detail["discriminator"] == 1234


async def test_identify_commission_not_ours(hass: HomeAssistant) -> None:
    """A code whose IP does not advertise _invis is not ours."""
    code = _make_code()
    with (
        patch(
            "custom_components.invisoutlet.commission.async_find_commissionable_ip",
            AsyncMock(return_value="10.0.0.5"),
        ),
        patch(
            "custom_components.invisoutlet.commission.async_ip_advertises_invis",
            AsyncMock(return_value=False),
        ),
    ):
        detail = await async_identify_commission(hass, code)
    assert detail["is_invisoutlet"] is False


async def test_identify_commission_bad_code(hass: HomeAssistant) -> None:
    """A bad code is reported, never raised, and is not ours."""
    detail = await async_identify_commission(hass, "not-a-code")
    assert detail["is_invisoutlet"] is False
    assert "error" in detail


async def test_find_commissionable_ip(hass: HomeAssistant) -> None:
    """The resolver returns the matched advertisement's address, or None."""
    info = MagicMock()
    info.parsed_addresses.return_value = ["10.0.0.9"]
    with patch(
        "custom_components.invisoutlet.commission._async_browse_match",
        AsyncMock(return_value=info),
    ):
        assert await async_find_commissionable_ip(hass, 1234) == "10.0.0.9"

    with patch(
        "custom_components.invisoutlet.commission._async_browse_match",
        AsyncMock(return_value=None),
    ):
        assert await async_find_commissionable_ip(hass, 1234) is None


async def test_ip_advertises_invis(hass: HomeAssistant) -> None:
    """The check is True when a matching _invis advertisement is found."""
    with patch(
        "custom_components.invisoutlet.commission._async_browse_match",
        AsyncMock(return_value=MagicMock()),
    ):
        assert await async_ip_advertises_invis(hass, "10.0.0.9") is True

    with patch(
        "custom_components.invisoutlet.commission._async_browse_match",
        AsyncMock(return_value=None),
    ):
        assert await async_ip_advertises_invis(hass, "10.0.0.9") is False


async def test_setup_registers_commands(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Loading the integration registers the interceptor and finish command."""
    await init_integration(hass, mock_config_entry)
    handlers = hass.data[ws_const.DOMAIN]
    assert COMMISSION_COMMAND in handlers
    assert FINISHED_COMMAND in handlers


async def test_intercept_delegates_unclaimed(hass: HomeAssistant) -> None:
    """The wrapper is registered last; async_delegate reaches the prior handler."""
    assert await async_setup_component(hass, "websocket_api", {})
    calls: list[dict] = []

    def _delegate(hass_, connection, msg):
        calls.append(msg)

    websocket_api.async_register_command(
        hass, "test/cmd", _delegate, vol.Schema({}, extra=vol.ALLOW_EXTRA)
    )

    @websocket_api.websocket_command({vol.Required("type"): "test/cmd"})
    @websocket_api.async_response
    async def _wrapper(hass_, connection, msg):
        pass

    async_intercept_command(hass, "test/cmd", _wrapper)
    assert hass.data[ws_const.DOMAIN]["test/cmd"][0] is _wrapper

    async_delegate(hass, "test/cmd", MagicMock(), {"id": 1, "type": "test/cmd"})
    assert calls == [{"id": 1, "type": "test/cmd"}]


async def test_ws_commission_claims_ours(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """The registered matter/commission handler claims ours and fires the event."""
    await init_integration(hass, mock_config_entry)
    client = await hass_ws_client(hass)
    events = async_capture_events(hass, EVENT_COMMISSIONED)

    with (
        patch(
            "custom_components.invisoutlet.commission.async_find_commissionable_ip",
            AsyncMock(return_value="10.0.0.77"),
        ),
        patch(
            "custom_components.invisoutlet.commission.async_ip_advertises_invis",
            AsyncMock(return_value=True),
        ),
    ):
        await client.send_json_auto_id(
            {"type": COMMISSION_COMMAND, "code": _make_code()}
        )
        msg = await client.receive_json()

    assert msg["success"]
    assert len(events) == 1
    assert events[0].data["ip"] == "10.0.0.77"


async def test_ws_commission_delegates_when_not_ours(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A code that isn't ours is delegated; with no Matter handler that errors."""
    await init_integration(hass, mock_config_entry)
    client = await hass_ws_client(hass)

    with patch(
        "custom_components.invisoutlet.commission.async_find_commissionable_ip",
        AsyncMock(return_value=None),
    ):
        await client.send_json_auto_id(
            {"type": COMMISSION_COMMAND, "code": _make_code()}
        )
        msg = await client.receive_json()

    assert not msg["success"]
    assert msg["error"]["code"] == ws_const.ERR_UNKNOWN_COMMAND


async def test_ws_finish_relays_name(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """The finish command relays the phone-set name onto the bus."""
    await init_integration(hass, mock_config_entry)
    client = await hass_ws_client(hass)
    events = async_capture_events(hass, EVENT_COMMISSION_FINISHED)

    await client.send_json_auto_id(
        {"type": FINISHED_COMMAND, "success": True, "name": "Phone Name"}
    )
    msg = await client.receive_json()

    assert msg["success"]
    assert len(events) == 1
    assert events[0].data == {"success": True, "name": "Phone Name"}


async def test_intercept_reasserts_on_matter_load(hass: HomeAssistant) -> None:
    """Adding Matter at runtime re-asserts our wrapper and captures its handler."""
    assert await async_setup_component(hass, "websocket_api", {})

    @websocket_api.websocket_command({vol.Required("type"): "test/reassert"})
    @websocket_api.async_response
    async def _wrapper(hass_, connection, msg):
        pass

    async_intercept_command(hass, "test/reassert", _wrapper, reassert_domain="matter")
    assert hass.data[ws_const.DOMAIN]["test/reassert"][0] is _wrapper

    # Matter loads at runtime and registers its own handler, clobbering ours.
    matter_calls: list[dict] = []

    def _matter_handler(hass_, connection, msg):
        matter_calls.append(msg)

    websocket_api.async_register_command(
        hass, "test/reassert", _matter_handler, vol.Schema({}, extra=vol.ALLOW_EXTRA)
    )
    assert hass.data[ws_const.DOMAIN]["test/reassert"][0] is _matter_handler

    # The Matter entry reaching LOADED fires this signal; we re-assert on top.
    async_dispatcher_send(
        hass,
        SIGNAL_CONFIG_ENTRY_CHANGED,
        ConfigEntryChange.UPDATED,
        MockConfigEntry(domain="matter"),
    )
    await hass.async_block_till_done()

    assert hass.data[ws_const.DOMAIN]["test/reassert"][0] is _wrapper
    # Non-ours now delegates to Matter's captured handler.
    async_delegate(
        hass, "test/reassert", MagicMock(), {"id": 1, "type": "test/reassert"}
    )
    assert matter_calls == [{"id": 1, "type": "test/reassert"}]


async def _init_commission_flow(hass: HomeAssistant) -> str:
    """Open the add menu and pick 'commission'; return the flow id on the spinner."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "commission"}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    return result["flow_id"]


async def test_commission_flow_lands_on_name_prefilled(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_setup_entry: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Firing the interceptor + finish events advances to the pre-filled name step."""
    mock_config_entry.add_to_hass(hass)
    mock_client.get_device_info.return_value.serial_number = "SN_NEW"

    flow_id = await _init_commission_flow(hass)

    # Stand in for the app: provisioning event (IP), then finish (name).
    hass.bus.async_fire(
        EVENT_COMMISSIONED, {"is_invisoutlet": True, "ip": "10.0.0.77"}
    )
    hass.bus.async_fire(
        EVENT_COMMISSION_FINISHED, {"success": True, "name": "Phone Name"}
    )
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_configure(flow_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "name"
    suggested = {
        marker.schema: marker.description.get("suggested_value")
        for marker in result["data_schema"].schema
        if getattr(marker, "description", None)
    }
    assert suggested[CONF_NAME] == "Phone Name"

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_NAME: "Phone Name"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "outlet_added"
    assert mock_config_entry.data[CONF_OUTLETS]["SN_NEW"][CONF_NAME] == "Phone Name"
    # A freshly commissioned outlet gets one post-provisioning reboot.
    mock_client.restart.assert_awaited_once()


async def test_commission_flow_cancel_aborts(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_setup_entry: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Finish without a provisioning event (cancelled) aborts the flow."""
    mock_config_entry.add_to_hass(hass)

    flow_id = await _init_commission_flow(hass)

    # Cancel: the app reports finished, but nothing was provisioned.
    hass.bus.async_fire(
        EVENT_COMMISSION_FINISHED, {"success": True, "name": None}
    )
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_configure(flow_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "commission_failed"
