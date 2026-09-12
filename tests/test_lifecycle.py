"""Exercise setup rollback, config flow and camera failure boundaries."""

import asyncio
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryNotReady
from custom_components import blink_live_proxy as integration
from custom_components.blink_live_proxy import camera, config_flow
from custom_components.blink_live_proxy.const import DOMAIN
from tests import test_blink_live_proxy_camera as fixtures


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_selects_loaded_entry_and_unloads(self):
        runtime = NS(api=NS(cameras={}))
        entries = NS(
            async_entries=Mock(
                return_value=[
                    NS(state=ConfigEntryState.NOT_LOADED),
                    NS(state=ConfigEntryState.LOADED, runtime_data=None),
                    NS(state=ConfigEntryState.LOADED, runtime_data=runtime),
                ]
            ),
            async_forward_entry_setups=AsyncMock(),
            async_unload_platforms=AsyncMock(return_value=False),
        )
        hass = NS(data={}, config_entries=entries)
        entry = NS(entry_id="proxy")
        self.assertTrue(await integration.async_setup_entry(hass, entry))
        self.assertIs(hass.data[DOMAIN]["proxy"], runtime)
        self.assertFalse(await integration.async_unload_entry(hass, entry))
        self.assertIn("proxy", hass.data[DOMAIN])
        entries.async_unload_platforms.return_value = True
        hass.data[DOMAIN]["other"] = runtime
        self.assertTrue(await integration.async_unload_entry(hass, entry))
        self.assertEqual(hass.data[DOMAIN], {"other": runtime})
        self.assertTrue(
            await integration.async_unload_entry(hass, NS(entry_id="other"))
        )
        self.assertNotIn(DOMAIN, hass.data)

    async def test_not_ready_and_setup_rollback(self):
        entries = NS(
            async_entries=Mock(return_value=[]),
            async_forward_entry_setups=AsyncMock(side_effect=RuntimeError("platform")),
        )
        hass = NS(data={}, config_entries=entries)
        entry = NS(entry_id="proxy")
        with self.assertRaises(ConfigEntryNotReady):
            await integration.async_setup_entry(hass, entry)
        entries.async_entries.return_value = [
            NS(state=ConfigEntryState.LOADED, runtime_data=object())
        ]
        for existing in ({}, {"other": "keep"}):
            hass.data = {DOMAIN: dict(existing)}
            with self.assertRaisesRegex(RuntimeError, "platform"):
                await integration.async_setup_entry(hass, entry)
            self.assertEqual(hass.data, {DOMAIN: existing} if existing else {})

    async def test_user_flow_form_and_creation(self):
        flow = config_flow.BlinkLiveProxyConfigFlow()
        with (
            patch.object(flow, "async_set_unique_id", AsyncMock()),
            patch.object(flow, "_abort_if_unique_id_configured"),
        ):
            result = await flow.async_step_user()
            self.assertEqual(result["step_id"], "user")
            result = await flow.async_step_user({})
            self.assertEqual(result["data"], {})
            self.assertEqual(result["title"], "Blink Live Proxy")


class CameraFailureTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.BlinkLiveProxyCameraTests.setUp

    async def test_platform_and_properties(self):
        self.coordinator.api = NS(cameras={"outside": self.camera})
        entities = []
        await camera.async_setup_entry(
            NS(data={DOMAIN: {"entry": self.coordinator}}),
            NS(entry_id="entry"),
            entities.extend,
        )
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].unique_id, "serial-live-proxy")
        self.assertTrue(self.entity.available)
        self.coordinator.last_update_success = False
        self.assertFalse(self.entity.available)
        self.assertEqual(self.entity.brand, "Blink")
        self.assertEqual(self.entity.model, "catalina")

    async def test_snapshot_empty_active_stream_and_failure(self):
        self.camera.image_from_cache = None
        self.entity._livestream = self.live
        with patch.object(camera, "SNAPSHOT_REFRESH_DELAY_SECONDS", 0):
            self.assertIsNone(await self.entity.async_camera_image())
            await self.entity._snapshot_task
            self.camera.snap_picture.assert_not_awaited()
            self.assertIsNone(self.entity._snapshot_task)
            self.entity._livestream = None
            self.camera.snap_picture.side_effect = RuntimeError("snapshot")
            with self.assertLogs(camera.__name__, "ERROR"):
                await self.entity._async_refresh_snapshot()
            self.camera.snap_picture.assert_awaited_once()

    async def test_retry_exhaustion(self):
        self.camera.init_livestream.side_effect = KeyError("server")
        with patch.object(camera, "LIVESTREAM_RETRY_DELAY_SECONDS", 0):
            with self.assertRaises(KeyError):
                await self.entity._async_start_livestream()
        self.assertEqual(
            self.camera.init_livestream.await_count, camera.LIVESTREAM_START_ATTEMPTS
        )

    async def test_feed_failure_cleans_owned_stream_only(self):
        failed = NS(feed=AsyncMock(side_effect=RuntimeError("feed")), stop=Mock())
        self.entity._livestream = failed
        with self.assertLogs(camera.__name__, "ERROR"):
            await self.entity._async_run_livestream(failed)
        self.assertIsNone(self.entity._livestream)
        failed.stop.assert_called_once()
        self.entity._livestream = self.live
        with self.assertLogs(camera.__name__, "ERROR"):
            await self.entity._async_run_livestream(failed)
        self.assertIs(self.entity._livestream, self.live)

    async def test_feed_cancel_and_removal_cancel_background_work(self):
        self.entity._livestream = self.live
        self.entity._feed_task = asyncio.create_task(
            self.entity._async_run_livestream(self.live)
        )
        await asyncio.sleep(0)
        await self.entity.async_camera_image()
        await asyncio.sleep(0)
        with patch.object(
            camera.Camera, "async_will_remove_from_hass", AsyncMock()
        ) as parent:
            await self.entity.async_will_remove_from_hass()
            parent.assert_awaited_once()
        self.assertTrue(self.live.stopped)
        self.assertIsNone(self.entity._feed_task)
        self.assertIsNone(self.entity._snapshot_task)
        with patch.object(camera.Camera, "async_will_remove_from_hass", AsyncMock()):
            await self.entity.async_will_remove_from_hass()

    async def test_attach_start_failure_closes_client(self):
        self.camera.init_livestream.side_effect = RuntimeError("start")
        for closing in (False, True):
            writer = NS(
                is_closing=Mock(return_value=closing),
                close=Mock(),
                wait_closed=AsyncMock(),
            )
            with self.assertLogs(camera.__name__, "ERROR"):
                await self.entity._async_handle_stream_client(Mock(), writer)
            self.assertEqual(writer.close.call_count, int(not closing))

    async def test_attach_cancellation_propagates(self):
        self.camera.init_livestream.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.entity._async_handle_stream_client(Mock(), Mock())

    async def test_disconnected_startup_cancels_pending_join(self):
        live = NS(clients=[], join=AsyncMock(side_effect=lambda *_: None))

        async def pending(*_):
            await asyncio.Event().wait()

        live.join.side_effect = pending
        self.camera.init_livestream.return_value = live
        writer = NS(
            is_closing=Mock(return_value=False), close=Mock(), wait_closed=AsyncMock()
        )
        with self.assertLogs(camera.__name__, "ERROR"):
            await self.entity._async_handle_stream_client(Mock(), writer)
        writer.close.assert_called_once()
        self.assertIsNone(self.entity._feed_task)
