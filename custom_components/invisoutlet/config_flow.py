"""Config flow for the InvisOutlet integration."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_SYSTEM,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import discovery_flow
from homeassistant.helpers.selector import AreaSelector
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from invisoutlet import InvisOutletClient, InvisOutletError

from .const import (
    CONF_AREA,
    CONF_EFFECTS,
    CONF_ENTRY_TYPE,
    CONF_OUTLETS,
    DOMAIN,
    ENTRY_TYPE_HUB,
    MANUFACTURER,
    SUBENTRY_AURA_EFFECT,
)

STEP_OUTLET_DATA_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})
OUTLET_NAME_SCHEMA = vol.Schema(
    {vol.Required(CONF_NAME): str, vol.Optional(CONF_AREA): AreaSelector()}
)
AURA_EFFECT_SCHEMA = vol.Schema({vol.Required(CONF_NAME): str})


def _named_outlet(outlet: dict[str, Any], user_input: dict[str, Any]) -> dict[str, Any]:
    """The outlet config with the chosen device name (and area, if picked)."""
    named = {**outlet, CONF_NAME: user_input[CONF_NAME]}
    if area := user_input.get(CONF_AREA):
        named[CONF_AREA] = area
    return named


def _previously_known(hass: HomeAssistant, serial: str) -> bool:
    """Whether this outlet was configured before (a tombstoned device exists).

    Re-adding it restores the old identity — name, area, entity ids — so the
    flow skips the naming step for it.
    """
    dev_reg = dr.async_get(hass)
    return dev_reg.deleted_devices.get_entry({(DOMAIN, serial)}, None) is not None


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
        self._probed: dict[str, Any] | None = None

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

    async def async_step_system(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the hub entry in the background (never user-visible).

        Started by ``_async_add_outlet`` when no hub exists yet. Because the
        user-facing flow aborts instead of creating the entry itself, the
        stock entry-created dialog never shows.
        """
        assert user_input is not None
        if self._find_hub() is not None:
            # The hub appeared while this flow was queued: append instead.
            return await self._async_add_outlet(
                user_input["serial"], user_input["outlet"]
            )
        return self.async_create_entry(
            title="InvisOutlet Devices",
            data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_HUB,
                CONF_OUTLETS: {user_input["serial"]: user_input["outlet"]},
            },
        )

    async def _async_add_outlet(
        self, serial: str, outlet: dict[str, Any]
    ) -> ConfigFlowResult:
        """Add the outlet to the hub, creating the hub in the background.

        Always aborts: the hub entry itself is only ever created by the
        system-source flow above, so no add ever surfaces the stock dialog.
        """
        hub = self._find_hub()
        if hub is None:
            discovery_flow.async_create_flow(
                self.hass,
                DOMAIN,
                context={"source": SOURCE_SYSTEM},
                data={"serial": serial, "outlet": outlet},
            )
            return self.async_abort(reason="outlet_added")

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
        """Add an outlet by host, then name it (creates the hub if needed)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                serial, outlet = await _probe_outlet(user_input[CONF_HOST])
            except InvisOutletError:
                errors["base"] = "cannot_connect"
            else:
                hub = self._find_hub()
                if hub is not None and serial in hub.data.get(CONF_OUTLETS, {}):
                    return self.async_abort(reason="already_configured")
                if _previously_known(self.hass, serial):
                    # Re-add: the old identity restores; no naming step.
                    return await self._async_add_outlet(serial, outlet)
                self._probed = {"serial": serial, "outlet": outlet}
                return await self.async_step_name()

        return self.async_show_form(
            step_id="outlet", data_schema=STEP_OUTLET_DATA_SCHEMA, errors=errors
        )

    async def async_step_name(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name the outlet's device, then add it."""
        probed = self._probed
        assert probed is not None
        if user_input is not None:
            return await self._async_add_outlet(
                probed["serial"], _named_outlet(probed["outlet"], user_input)
            )
        return self.async_show_form(
            step_id="name",
            data_schema=self.add_suggested_values_to_schema(
                OUTLET_NAME_SCHEMA,
                {CONF_NAME: f"InvisOutlet {probed['serial']}"},
            ),
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
        """Confirm and name a discovered outlet.

        A previously known outlet restores its old identity, so it gets a
        plain confirm with no naming fields.
        """
        assert self._discovered is not None
        known = _previously_known(self.hass, self._discovered["serial"])
        if user_input is not None:
            outlet: dict[str, Any] = {CONF_HOST: self._discovered["host"]}
            if not known:
                outlet = _named_outlet(outlet, user_input)
            return await self._async_add_outlet(self._discovered["serial"], outlet)

        if known:
            self._set_confirm_only()
            return self.async_show_form(
                step_id="zeroconf_confirm",
                description_placeholders={"name": self._discovered["title"]},
            )
        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=self.add_suggested_values_to_schema(
                OUTLET_NAME_SCHEMA, {CONF_NAME: self._discovered["title"]}
            ),
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
