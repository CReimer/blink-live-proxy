"""Config flow for Blink Live Proxy."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN


class BlinkLiveProxyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Blink Live Proxy config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Blink Live Proxy", data={})

        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))
