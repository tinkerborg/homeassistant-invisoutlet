"""Base entity for the InvisOutlet integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import InvisOutletCoordinator


class InvisOutletEntity(CoordinatorEntity[InvisOutletCoordinator]):
    """Base entity tying everything to the device registry entry."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: InvisOutletCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        info = coordinator.device_info
        connections = {(CONNECTION_NETWORK_MAC, info.mac)} if info.mac else set()
        name = " ".join(p for p in (info.device, info.serial_number) if p)
        # The IP follows DHCP changes: zeroconf re-discovery updates CONF_HOST and
        # reloads the entry, which recreates this configuration_url with the new IP.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, info.serial_number)},
            connections=connections,
            manufacturer=MANUFACTURER,
            model=info.device or None,
            sw_version=info.fw_rev,
            serial_number=info.serial_number,
            name=name or MANUFACTURER,
            configuration_url=f"http://{info.host}" if info.host else None,
        )
