"""Lifecycle tests for Blink Live Proxy cameras."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from custom_components.blink_live_proxy.camera import BlinkLiveProxyCamera


class FakeLiveStream:
    """Small controllable Blink live-stream stand-in."""

    def __init__(self) -> None:
        self.clients = []
        self.command_id = 1
        self.feed_release = asyncio.Event()
        self.stopped = False

    async def feed(self) -> None:
        await self.feed_release.wait()

    async def join(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.clients.append(writer)
        try:
            await reader.read()
        finally:
            self.clients.remove(writer)
            if not writer.is_closing():
                writer.close()
            await writer.wait_closed()
            if not self.clients:
                self.stop()

    def stop(self) -> None:
        self.stopped = True
        self.feed_release.set()
        for writer in self.clients:
            writer.close()


class BlinkLiveProxyCameraTests(unittest.IsolatedAsyncioTestCase):
    """Verify snapshot deduplication and stream reuse."""

    def setUp(self) -> None:
        self.live = FakeLiveStream()
        self.camera = SimpleNamespace(
            serial="serial",
            camera_type="catalina",
            version="1",
            name="outside",
            image_from_cache=b"old",
            snap_picture=AsyncMock(),
            init_livestream=AsyncMock(return_value=self.live),
        )
        self.coordinator = SimpleNamespace(last_update_success=True)
        self.entity = BlinkLiveProxyCamera(self.coordinator, "outside", self.camera)
        self.entity.hass = SimpleNamespace(
            async_create_task=lambda coro, _name: asyncio.create_task(coro)
        )

    async def test_concurrent_snapshot_requests_are_deduplicated(self) -> None:
        refresh_started = asyncio.Event()
        refresh_release = asyncio.Event()

        async def refresh() -> None:
            refresh_started.set()
            await refresh_release.wait()
            self.camera.image_from_cache = b"new"

        self.camera.snap_picture.side_effect = refresh
        with patch(
            "custom_components.blink_live_proxy.camera.SNAPSHOT_REFRESH_DELAY_SECONDS",
            0,
        ):
            images = await asyncio.gather(
                self.entity.async_camera_image(), self.entity.async_camera_image()
            )
        self.assertEqual(images, [b"old", b"old"])
        await asyncio.wait_for(refresh_started.wait(), timeout=1)
        self.camera.snap_picture.assert_awaited_once()

        refresh_release.set()
        snapshot_task = self.entity._snapshot_task
        self.assertIsNotNone(snapshot_task)
        await snapshot_task
        self.assertEqual(await self.entity.async_camera_image(), b"new")
        self.camera.snap_picture.assert_awaited_once()

    async def test_stream_client_cancels_delayed_snapshot_refresh(self) -> None:
        self.assertEqual(await self.entity.async_camera_image(), b"old")
        self.camera.snap_picture.assert_not_awaited()

        source = await self.entity.stream_source()
        host, port = source.removeprefix("tcp://").split(":")
        _reader, writer = await asyncio.open_connection(host, int(port))
        for _ in range(50):
            if self.camera.init_livestream.await_count:
                break
            await asyncio.sleep(0.01)

        self.camera.snap_picture.assert_not_awaited()
        self.camera.init_livestream.assert_awaited_once()
        writer.close()
        await writer.wait_closed()
        await self.entity._async_stop_streaming()

    async def test_relay_is_stable_and_blink_starts_for_real_client(self) -> None:
        first, second = await asyncio.gather(
            self.entity.stream_source(), self.entity.stream_source()
        )
        self.assertEqual(first, second)
        self.camera.init_livestream.assert_not_awaited()

        host, port = first.removeprefix("tcp://").split(":")
        _reader, writer = await asyncio.open_connection(host, int(port))
        for _ in range(50):
            if self.camera.init_livestream.await_count:
                break
            await asyncio.sleep(0.01)
        self.camera.init_livestream.assert_awaited_once()

        writer.close()
        await writer.wait_closed()
        await self.entity._async_stop_streaming()
        self.assertTrue(self.live.stopped)

    async def test_missing_liveview_server_is_retried(self) -> None:
        self.camera.init_livestream.side_effect = [KeyError("server"), self.live]

        with patch(
            "custom_components.blink_live_proxy.camera.LIVESTREAM_RETRY_DELAY_SECONDS",
            0,
        ):
            livestream = await self.entity._async_start_livestream()

        self.assertIs(livestream, self.live)
        self.assertEqual(self.camera.init_livestream.await_count, 2)

    async def test_unrelated_key_error_is_not_retried(self) -> None:
        self.camera.init_livestream.side_effect = KeyError("command_id")

        with self.assertRaisesRegex(KeyError, "command_id"):
            await self.entity._async_start_livestream()

        self.camera.init_livestream.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
