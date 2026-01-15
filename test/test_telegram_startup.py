import os
import sys
import time
import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

# Add project root to path to allow top-level imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Set a dummy env var for db before other imports
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['APP_KEY'] = 'test-key'

# Monkey patch for eventlet simulation
import eventlet
eventlet.monkey_patch()

# Now import the service, it will see the patched environment
from services.telegram_bot_service import TelegramBotService

class TestTelegramBotStartup(unittest.TestCase):

    def setUp(self):
        """Set up mocks for database and external API calls."""
        # Reset the service instance to ensure clean state for each test
        self.service = TelegramBotService()

        # Mock database functions
        self.get_bot_config_patch = patch('services.telegram_bot_service.get_bot_config')
        self.update_bot_config_patch = patch('services.telegram_bot_service.update_bot_config')

        self.mock_get_bot_config = self.get_bot_config_patch.start()
        self.mock_update_bot_config = self.update_bot_config_patch.start()

        # Mock the telegram Application and its methods
        self.app_builder_patch = patch('telegram.ext.Application.builder')
        self.mock_app_builder = self.app_builder_patch.start()

        mock_app = MagicMock()
        mock_updater = MagicMock()
        mock_app.updater = mock_updater

        self.mock_app_builder.return_value.token.return_value.build.return_value = mock_app

        # Configure the mock bot to run without actually polling
        async def mock_start_polling(*args, **kwargs):
            self.service.is_running = True
            while not self.service._stop_event.is_set():
                await asyncio.sleep(0.01)

        # Use AsyncMock for coroutine methods
        mock_updater.start_polling = AsyncMock(side_effect=mock_start_polling)
        mock_app.initialize = AsyncMock(return_value=None)
        mock_app.start = AsyncMock(return_value=None)
        mock_app.stop = AsyncMock(return_value=None)
        mock_app.shutdown = AsyncMock(return_value=None)
        mock_updater.stop = AsyncMock(return_value=None)

        # Mock the synchronous request for token validation
        self.requests_get_patch = patch('requests.get')
        self.mock_requests_get = self.requests_get_patch.start()
        self.mock_requests_get.return_value.status_code = 200
        self.mock_requests_get.return_value.json.return_value = {
            'ok': True,
            'result': {'id': 12345, 'is_bot': True, 'first_name': 'Test Bot', 'username': 'TestBot'}
        }

    def tearDown(self):
        """Stop all patches."""
        self.get_bot_config_patch.stop()
        self.update_bot_config_patch.stop()
        self.app_builder_patch.stop()
        self.requests_get_patch.stop()
        if self.service.is_running:
            self.service.stop_bot()

    def test_bot_starts_and_stops_cleanly_in_eventlet_env(self):
        """
        Verify that the bot starts and stops without event loop errors
        in a simulated eventlet environment.
        """
        self.mock_get_bot_config.return_value = {'bot_token': 'dummy_token', 'is_active': True}

        # 1. Initialize the bot
        success, msg = self.service.initialize_bot_sync(token='dummy_token')
        self.assertTrue(success, f"Bot initialization failed: {msg}")

        # 2. Start the bot
        start_success, start_msg = self.service.start_bot()
        self.assertTrue(start_success, f"Bot startup failed: {start_msg}")
        self.assertTrue(self.service.is_running)

        # 3. Stop the bot
        stop_success, stop_msg = self.service.stop_bot()
        self.assertTrue(stop_success, f"Bot stop failed: {stop_msg}")
        self.assertFalse(self.service.is_running)

        # 4. Join the thread to ensure it has terminated
        if self.service.bot_thread:
            self.service.bot_thread.join(timeout=2)
            self.assertFalse(self.service.bot_thread.is_alive(), "Bot thread did not terminate")

if __name__ == '__main__':
    unittest.main()