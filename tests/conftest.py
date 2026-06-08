"""Fixtures for the InvisOutlet integration tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from invisoutlet import (
    AvailableUpdates,
    DeviceConfig,
    DeviceInfo,
    FirmwareRelease,
    FirmwareUpdate,
    NightlightState,
    OutletStatus,
    SensorData,
    SubDeviceInfo,
)
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.invisoutlet.const import (
    CONF_EFFECTS,
    CONF_ENTRY_TYPE,
    CONF_OUTLETS,
    DOMAIN,
    ENTRY_TYPE_HUB,
    SUBENTRY_AURA_EFFECT,
)

SERIAL = "SN12345"
HOST = "10.0.0.9"
EFFECT_ID = "effect0001"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Enable the custom integration for every test."""


def make_device_info(*, with_deco: bool = False, deco_type: str | None = None) -> DeviceInfo:
    """Build a DeviceInfo, optionally with an attached faceplate."""
    sub_device = None
    if with_deco:
        sub_device = SubDeviceInfo(
            serial_number="DECO999",
            mac="11:22:33:44:55:66",
            device="InvisDeco",
            device_type=deco_type,
            hw_rev="1.0",
            fw_rev="3.0",
            online=True,
        )
    return DeviceInfo(
        serial_number=SERIAL,
        mac="aa:bb:cc:dd:ee:ff",
        device="InvisOutlet",
        hw_rev="1.0",
        fw_rev="2.0",
        host=HOST,
        port=80,
        sub_device=sub_device,
    )


def make_sensor_data() -> SensorData:
    """A full sensor payload so every sensor/binary sensor is 'supported'."""
    return SensorData(
        temperature=21.5,
        humidity=40.0,
        air_quality_index=75,
        co2=600,
        voc=0.5,
        pressure=101325,
        illuminance=120.0,
        distance=150,
        occupancy_state=1,
        movement_energy=10,
    )


def _configure_client(client: AsyncMock, *, with_deco: bool, deco_type: str | None) -> None:
    """Give a mock client sensible return values for the whole read surface."""
    client.host = HOST
    client.get_device_info.return_value = make_device_info(
        with_deco=with_deco, deco_type=deco_type
    )
    client.get_config.return_value = DeviceConfig(
        outlet_power_indicator_on=True,
        pm_indicator_brightness=50,
        capacitive_ctrl=True,
        magic_touch_ctrl=False,
        aqi_color_rgb_feature=True,
        motion_away_feature=False,
        adaptive_nightlight_feature=True,
        occupancy_nightlight_feature=False,
        adaptive_min_brightness=5,
        adaptive_max_brightness=80,
    )
    client.get_outlet_status.return_value = OutletStatus(outlets=[True, False])
    client.get_sensor_data.return_value = make_sensor_data()
    client.get_nightlight.return_value = NightlightState(mode=1, brightness=75)
    client.get_color.side_effect = None
    from invisoutlet import ColorLightState

    client.get_color.return_value = ColorLightState(light=5, mode=1, leds=[])
    client.get_available_updates.return_value = AvailableUpdates(
        im=FirmwareUpdate(fw_rev="2.0", available_fw_rev="2.0")
    )
    client.check_firmware.return_value = None
    # Synchronous registrars returning an unsubscribe callback.
    for registrar in (
        "on_connect",
        "on_disconnect",
        "on_sensor_data",
        "on_outlet_status",
        "on_ota_progress",
        "on_ota_result",
        "on_message",
    ):
        setattr(client, registrar, MagicMock(return_value=lambda: None))


def _patched_client(client: AsyncMock) -> Generator[AsyncMock]:
    """Patch every InvisOutletClient construction site to return ``client``."""
    with (
        patch(
            "custom_components.invisoutlet.config_flow.InvisOutletClient",
            return_value=client,
        ),
        patch(
            "custom_components.invisoutlet.InvisOutletClient",
            return_value=client,
        ),
    ):
        yield client


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """An outlet with no attached faceplate."""
    client = AsyncMock()
    _configure_client(client, with_deco=False, deco_type=None)
    yield from _patched_client(client)


@pytest.fixture
def mock_client_deco() -> Generator[AsyncMock]:
    """An outlet with an attached InvisDeco faceplate and an available update."""
    client = AsyncMock()
    _configure_client(client, with_deco=True, deco_type=None)
    client.check_firmware.return_value = FirmwareRelease(
        current_fw_rev="3.0",
        available_fw_rev="3.1",
        ota_bin_url="http://x/fw.bin",
        message="Line one\nLine two",
    )
    yield from _patched_client(client)


@pytest.fixture
def mock_client_aura() -> Generator[AsyncMock]:
    """An outlet with an attached Aura faceplate (color-array nightlight)."""
    client = AsyncMock()
    _configure_client(client, with_deco=True, deco_type="Aura")
    yield from _patched_client(client)


def registered_callback(mock_client: AsyncMock, registrar: str) -> object:
    """The callback the coordinator handed to ``client.<registrar>``."""
    return getattr(mock_client, registrar).call_args[0][0]


def message_handler(mock_client: AsyncMock, callback_id: int) -> object:
    """The handler registered via ``client.on_message(callback_id, handler)``."""
    for call in mock_client.on_message.call_args_list:
        if call[0][0] == callback_id:
            return call[0][1]
    raise KeyError(callback_id)


async def push_sensor(
    hass: HomeAssistant, mock_client: AsyncMock, data: SensorData
) -> None:
    """Simulate the library pushing a sensor update (marks the faceplate online)."""
    registered_callback(mock_client, "on_sensor_data")(data)
    await hass.async_block_till_done()


async def push_outlets(
    hass: HomeAssistant, mock_client: AsyncMock, status: OutletStatus
) -> None:
    """Simulate the library pushing an outlet-status update."""
    registered_callback(mock_client, "on_outlet_status")(status)
    await hass.async_block_till_done()


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Prevent real entry setup so flow tests exercise only the flow."""
    with patch(
        "custom_components.invisoutlet.async_setup_entry", return_value=True
    ) as mock:
        yield mock


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A hub config entry holding a single outlet."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="InvisOutlet Devices",
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_HUB,
            CONF_OUTLETS: {SERIAL: {"host": HOST}},
        },
    )


@pytest.fixture
def mock_config_entry_with_effect() -> MockConfigEntry:
    """A hub entry with one outlet and one defined Aura effect."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="InvisOutlet Devices",
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_HUB,
            CONF_OUTLETS: {SERIAL: {"host": HOST}},
        },
        subentries_data=[
            ConfigSubentryData(
                data={
                    CONF_EFFECTS: {
                        EFFECT_ID: {
                            "name": "Sunset",
                            "mode": "rainbow",
                            "random": False,
                            "speed": 3,
                            "pixel_0": {
                                "on": True,
                                "hs": [200, 60],
                                "brightness": 200,
                                "temp": 4000,
                            },
                        }
                    }
                },
                subentry_type=SUBENTRY_AURA_EFFECT,
                title="InvisOutlet Aura Effects",
                unique_id=None,
            )
        ],
    )


async def init_integration(
    hass: HomeAssistant, entry: MockConfigEntry
) -> MockConfigEntry:
    """Add the entry to hass and run setup, returning the loaded entry."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
