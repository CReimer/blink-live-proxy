"""Constants for the Blink Live Proxy integration."""

from homeassistant.const import Platform

DOMAIN = "blink_live_proxy"
PLATFORMS = [Platform.CAMERA]

SNAPSHOT_COOLDOWN_SECONDS = 30.0
SNAPSHOT_REFRESH_DELAY_SECONDS = 3.0
LIVESTREAM_START_ATTEMPTS = 3
LIVESTREAM_RETRY_DELAY_SECONDS = 2.0
