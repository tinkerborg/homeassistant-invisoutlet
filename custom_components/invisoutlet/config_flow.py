"""Config flow for the InvisOutlet integration."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from invisoutlet import InvisOutletClient, InvisOutletError

from .const import (
    CONF_EFFECTS,
    CONF_ENTRY_TYPE,
    CONF_OUTLETS,
    DOMAIN,
    ENTRY_TYPE_HUB,
    MANUFACTURER,
    SUBENTRY_AURA_EFFECT,
)

STEP_OUTLET_DATA_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})
AURA_EFFECT_SCHEMA = vol.Schema({vol.Required(CONF_NAME): str})


async def _probe_outlet(host: str) -> tuple[str, dict[str, Any]]:
    """Connect to an outlet, returning ``(serial, outlet_config)``.

    Raises :class:`InvisOutletError` if the outlet can't be reached.
    """
    client = InvisOutletClient(host)
    try:
        await client.connect()
        info = await client.get_device_info()
    finally:
        await client.close()
    return info.serial_number, {CONF_HOST: host}


class InvisOutletConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for InvisOutlet."""

    def __init__(self) -> None:
        """Initialize the flow."""
        self._discovered: dict[str, Any] | None = None

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Offer the Add Aura Effect button on the hub."""
        if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
            return {SUBENTRY_AURA_EFFECT: AuraEffectSubentryFlowHandler}
        return {}

    def _find_hub(self) -> ConfigEntry | None:
        """Return the single InvisOutlet hub entry, if it exists."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
                return entry
        return None

    async def _async_add_outlet(
        self, serial: str, outlet: dict[str, Any]
    ) -> ConfigFlowResult:
        """Create the hub with this outlet, or add it to the existing hub."""
        hub = self._find_hub()
        if hub is None:
            return self.async_create_entry(
                title="InvisOutlet Devices",
                data={CONF_ENTRY_TYPE: ENTRY_TYPE_HUB, CONF_OUTLETS: {serial: outlet}},
            )

        outlets = hub.data.get(CONF_OUTLETS, {})
        if serial in outlets:
            return self.async_abort(reason="already_configured")
        # Appending fires the hub's update listener, which reloads it and brings
        # up the new outlet's device.
        self.hass.config_entries.async_update_entry(
            hub, data={**hub.data, CONF_OUTLETS: {**outlets, serial: outlet}}
        )
        return self.async_abort(reason="outlet_added")

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Adding an entry manually means adding an outlet."""
        return await self.async_step_outlet(user_input)

    async def async_step_outlet(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add an outlet by host (creates the hub if needed)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                serial, outlet = await _probe_outlet(user_input[CONF_HOST])
            except InvisOutletError:
                errors["base"] = "cannot_connect"
            else:
                return await self._async_add_outlet(serial, outlet)

        return self.async_show_form(
            step_id="outlet", data_schema=STEP_OUTLET_DATA_SCHEMA, errors=errors
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle an outlet discovered over mDNS."""
        serial = discovery_info.properties.get("sn")
        if not serial:
            return self.async_abort(reason="no_serial")

        host = str(discovery_info.ip_address)
        # Already an outlet on the hub? Keep its host current and stop.
        hub = self._find_hub()
        if hub is not None:
            outlets = hub.data.get(CONF_OUTLETS, {})
            if serial in outlets:
                if outlets[serial].get(CONF_HOST) != host:
                    self.hass.config_entries.async_update_entry(
                        hub,
                        data={
                            **hub.data,
                            CONF_OUTLETS: {
                                **outlets,
                                serial: {**outlets[serial], CONF_HOST: host},
                            },
                        },
                    )
                return self.async_abort(reason="already_configured")

        await self.async_set_unique_id(serial)
        model = discovery_info.properties.get("device") or ""
        title = " ".join(p for p in (model, serial) if p) or MANUFACTURER
        self._discovered = {"serial": serial, "title": title, "host": host}
        self.context["title_placeholders"] = {"name": title}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered outlet to the hub."""
        assert self._discovered is not None
        if user_input is not None:
            return await self._async_add_outlet(
                self._discovered["serial"],
                {CONF_HOST: self._discovered["host"]},
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={"name": self._discovered["title"]},
        )


class AuraEffectSubentryFlowHandler(ConfigSubentryFlow):
    """Add an Aura effect, appended into the single shared Aura Effects subentry.

    The first add creates the subentry; every add after appends another effect
    (one device each) to the same subentry's data, so they group together
    instead of spawning a subentry per effect.
    """

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add an Aura effect."""
        if user_input is not None:
            effect = {CONF_NAME: user_input[CONF_NAME]}
            entry = self.hass.config_entries.async_get_entry(self.handler[0])
            assert entry is not None
            existing = entry.get_subentries_of_type(SUBENTRY_AURA_EFFECT)
            if existing:
                subentry = existing[0]
                effects = {**subentry.data.get(CONF_EFFECTS, {}), uuid4().hex: effect}
                self.hass.config_entries.async_update_subentry(
                    entry, subentry, data={CONF_EFFECTS: effects}
                )
            else:
                self.hass.config_entries.async_add_subentry(
                    entry,
                    ConfigSubentry(
                        data=MappingProxyType({CONF_EFFECTS: {uuid4().hex: effect}}),
                        subentry_type=SUBENTRY_AURA_EFFECT,
                        title="InvisOutlet Aura Effects",
                        unique_id=None,
                    ),
                )
            # The subentry now exists, so reload to bring the new effect's virtual
            # device up. (update_reload_and_abort is rejected on entries with
            # update listeners, which the hub has, so reload separately.)
            self.hass.config_entries.async_schedule_reload(entry.entry_id)
            return self.async_abort(reason="added")
        return self.async_show_form(step_id="user", data_schema=AURA_EFFECT_SCHEMA)
