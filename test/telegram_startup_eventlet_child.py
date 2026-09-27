"""Run the Telegram startup proof under eventlet outside pytest's process."""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["APP_KEY"] = "test-key"

import eventlet

eventlet.monkey_patch()

from services.telegram_bot_service import TelegramBotService


class TestTelegramBotStartup(unittest.TestCase):
    def setUp(self):
        self.service = TelegramBotService()
        self.get_bot_config_patch = patch("services.telegram_bot_service.get_bot_config")
        self.update_bot_config_patch = patch("services.telegram_bot_service.update_bot_config")
        self.mock_get_bot_config = self.get_bot_config_patch.start()
        self.mock_update_bot_config = self.update_bot_config_patch.start()

        self.app_builder_patch = patch("telegram.ext.Application.builder")
        self.mock_app_builder = self.app_builder_patch.start()
        mock_app = MagicMock()
        mock_updater = MagicMock()
        mock_app.updater = mock_updater
        self.mock_app_builder.return_value.token.return_value.build.return_value = mock_app

        async def mock_start_polling(*_args, **_kwargs):
            self.service.is_running = True
            while not self.service._stop_event.is_set():
                await asyncio.sleep(0.01)

        mock_updater.start_polling = AsyncMock(side_effect=mock_start_polling)
        mock_app.initialize = AsyncMock(return_value=None)
        mock_app.start = AsyncMock(return_value=None)
        mock_app.stop = AsyncMock(return_value=None)
        mock_app.shutdown = AsyncMock(return_value=None)
        mock_updater.stop = AsyncMock(return_value=None)

        self.httpx_client_patch = patch("utils.httpx_client.get_httpx_client")
        self.mock_get_httpx_client = self.httpx_client_patch.start()
        self.mock_get_httpx_client.return_value.get.return_value.status_code = 200
        self.mock_get_httpx_client.return_value.get.return_value.json.return_value = {
            "ok": True,
            "result": {
                "id": 12345,
                "is_bot": True,
                "first_name": "Test Bot",
                "username": "TestBot",
            },
        }

    def tearDown(self):
        self.get_bot_config_patch.stop()
        self.update_bot_config_patch.stop()
        self.app_builder_patch.stop()
        self.httpx_client_patch.stop()
        if self.service.is_running:
            self.service.stop_bot()

    def test_bot_starts_and_stops_cleanly_in_eventlet_env(self):
        self.mock_get_bot_config.return_value = {"bot_token": "dummy_token", "is_active": True}

        success, message = self.service.initialize_bot_sync(token="dummy_token")
        self.assertTrue(success, f"Bot initialization failed: {message}")

        start_success, start_message = self.service.start_bot()
        self.assertTrue(start_success, f"Bot startup failed: {start_message}")
        self.assertTrue(self.service.is_running)

        stop_success, stop_message = self.service.stop_bot()
        self.assertTrue(stop_success, f"Bot stop failed: {stop_message}")
        self.assertFalse(self.service.is_running)

        if self.service.bot_thread:
            self.service.bot_thread.join(timeout=2)
            self.assertFalse(self.service.bot_thread.is_alive(), "Bot thread did not terminate")


if __name__ == "__main__":
    unittest.main()
