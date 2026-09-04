"""Blink Live Proxy integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Blink Live Proxy from a config entry."""
    blink_entry = next(
        (
            candidate
            for candidate in hass.config_entries.async_entries("blink")
            if candidate.state is ConfigEntryState.LOADED
            and candidate.runtime_data is not None
        ),
        None,
    )
    if blink_entry is None:
        raise ConfigEntryNotReady("The Blink integration is not loaded")

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = blink_entry.runtime_data
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Blink Live Proxy config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hass.data[DOMAIN].pop(entry.entry_id)
    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)
    return True
