"""Camera entities for Blink Live Proxy."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic
from typing import Any

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DOMAIN,
    LIVESTREAM_RETRY_DELAY_SECONDS,
    LIVESTREAM_START_ATTEMPTS,
    SNAPSHOT_COOLDOWN_SECONDS,
    SNAPSHOT_REFRESH_DELAY_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Blink Live Proxy cameras."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        BlinkLiveProxyCamera(coordinator, name, camera)
        for name, camera in coordinator.api.cameras.items()
    )


class BlinkLiveProxyCamera(Camera):
    """Expose a Blink camera with snapshots and its experimental live stream."""

    _attr_content_type = "image/jpeg"
    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, coordinator: Any, name: str, camera: Any) -> None:
        """Initialize a Blink Live Proxy camera."""
        super().__init__()
        self._coordinator = coordinator
        self._camera = camera
        self._attr_name = name
        self._attr_suggested_object_id = f"{name}_stream"
        self._attr_unique_id = f"{camera.serial}-live-proxy"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, camera.serial)},
            manufacturer="Blink",
            model=camera.camera_type,
            name=f"{name} Live Proxy",
            serial_number=camera.serial,
            sw_version=camera.version,
        )
        self._last_snapshot_attempt = 0.0
        self._snapshot_task: asyncio.Task[None] | None = None
        self._stream_lock = asyncio.Lock()
        self._relay_server: asyncio.AbstractServer | None = None
        self._relay_url: str | None = None
        self._livestream: Any | None = None
        self._feed_task: asyncio.Task[None] | None = None

    @property
    def available(self) -> bool:
        """Return whether the shared Blink coordinator is available."""
        return bool(self._coordinator.last_update_success)

    @property
    def brand(self) -> str:
        """Return the camera brand."""
        return "Blink"

    @property
    def model(self) -> str:
        """Return the Blink model identifier."""
        return self._camera.camera_type

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the cached image immediately and refresh it in the background."""
        del width, height
        task = self._snapshot_task
        if (
            task is None
            and monotonic() - self._last_snapshot_attempt >= SNAPSHOT_COOLDOWN_SECONDS
        ):
            self._last_snapshot_attempt = monotonic()
            task = self.hass.async_create_task(
                self._async_refresh_snapshot(),
                f"Refresh Blink Live Proxy snapshot for {self._camera.name}",
            )
            self._snapshot_task = task

        image = self._camera.image_from_cache
        return bytes(image) if image is not None else None

    async def _async_refresh_snapshot(self) -> None:
        """Request a fresh Blink snapshot without blocking later HomeKit requests."""
        current_task = asyncio.current_task()
        try:
            await asyncio.sleep(SNAPSHOT_REFRESH_DELAY_SECONDS)
            if self._livestream is not None:
                return
            await self._camera.snap_picture()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "Failed to refresh Blink snapshot for %s", self._camera.name
            )
        finally:
            if self._snapshot_task is current_task:
                self._snapshot_task = None

    async def stream_source(self) -> str | None:
        """Return a stable local relay which starts Blink for real consumers."""
        async with self._stream_lock:
            if self._relay_server is None or not self._relay_server.is_serving():
                self._relay_server = await asyncio.start_server(
                    self._async_handle_stream_client, "127.0.0.1", 0
                )
                host, port = self._relay_server.sockets[0].getsockname()[:2]
                self._relay_url = f"tcp://{host}:{port}"
            return self._relay_url

    async def _async_handle_stream_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Attach a Home Assistant or HomeKit client to one Blink stream."""
        join_task: asyncio.Task[None] | None = None
        try:
            snapshot_task = self._snapshot_task
            if snapshot_task is not None and not snapshot_task.done():
                snapshot_task.cancel()
                try:
                    await snapshot_task
                except asyncio.CancelledError:
                    pass
            async with self._stream_lock:
                livestream = self._livestream
                if (
                    livestream is None
                    or self._feed_task is None
                    or self._feed_task.done()
                ):
                    livestream = await self._async_start_livestream()
                    self._livestream = livestream

                join_task = self.hass.async_create_task(
                    livestream.join(reader, writer),
                    f"Attach client to Blink stream for {self._camera.name}",
                )
                await asyncio.sleep(0)
                if self._feed_task is None or self._feed_task.done():
                    if not livestream.clients:
                        raise RuntimeError("Stream client disconnected during startup")
                    self._feed_task = self.hass.async_create_task(
                        self._async_run_livestream(livestream),
                        f"Proxy Blink live stream for {self._camera.name}",
                    )
            await join_task
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "Failed to attach stream client for %s", self._camera.name
            )
            if join_task is not None and not join_task.done():
                join_task.cancel()
                try:
                    await join_task
                except asyncio.CancelledError:
                    pass
            if not writer.is_closing():
                writer.close()
                await writer.wait_closed()

    async def _async_start_livestream(self) -> Any:
        """Start Blink liveview, retrying its observed transient busy response."""
        for attempt in range(1, LIVESTREAM_START_ATTEMPTS + 1):
            try:
                return await self._camera.init_livestream()
            except KeyError as err:
                if err.args != ("server",) or attempt == LIVESTREAM_START_ATTEMPTS:
                    raise
                _LOGGER.warning(
                    "Blink liveview returned no server for %s; retrying (%s/%s)",
                    self._camera.name,
                    attempt,
                    LIVESTREAM_START_ATTEMPTS,
                )
                await asyncio.sleep(LIVESTREAM_RETRY_DELAY_SECONDS)
        raise RuntimeError("Blink livestream retry loop exited unexpectedly")

    async def _async_run_livestream(self, livestream: Any) -> None:
        """Run one upstream Blink stream for all connected local consumers."""
        try:
            await livestream.feed()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Blink live stream failed for %s", self._camera.name)
        finally:
            livestream.stop()
            if self._livestream is livestream:
                self._livestream = None
                self._feed_task = None

    async def _async_stop_streaming(self) -> None:
        """Stop the local relay and any active upstream Blink stream."""
        relay_server = self._relay_server
        if relay_server is not None:
            relay_server.close()
            await relay_server.wait_closed()
        self._relay_server = None
        self._relay_url = None

        livestream = self._livestream
        task = self._feed_task
        if livestream is not None:
            livestream.stop()
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._livestream = None
        self._feed_task = None

    async def async_will_remove_from_hass(self) -> None:
        """Stop background work when the proxy camera is removed."""
        if self._snapshot_task is not None and not self._snapshot_task.done():
            self._snapshot_task.cancel()
            try:
                await self._snapshot_task
            except asyncio.CancelledError:
                pass
        async with self._stream_lock:
            await self._async_stop_streaming()
        await super().async_will_remove_from_hass()
