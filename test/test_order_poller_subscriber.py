"""
Tests for subscribers.order_poller_subscriber.

Verifies the EventBus subscriber that kicks the order/position poller
into fast mode on order.placed/modified/cancelled - decoupled from the
real database and poller via mocks, per the pattern already used by the
existing socketio/telegram subscribers.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from subscribers import order_poller_subscriber


def make_event(mode="live", api_key="test-api-key"):
    return SimpleNamespace(mode=mode, api_key=api_key)


class TestOnOrderPlaced:
    @patch("subscribers.order_poller_subscriber.trigger_fast_mode")
    @patch("subscribers.order_poller_subscriber.get_auth_token_broker")
    @patch("subscribers.order_poller_subscriber.verify_api_key")
    def test_triggers_fast_mode_for_live_order(self, mock_verify, mock_get_broker, mock_trigger):
        mock_verify.return_value = "user1"
        mock_get_broker.return_value = ("decrypted-token", "zerodha")

        order_poller_subscriber.on_order_placed(make_event(mode="live"))

        mock_trigger.assert_called_once_with("zerodha", "user1")

    @patch("subscribers.order_poller_subscriber.trigger_fast_mode")
    def test_does_not_trigger_for_analyze_mode(self, mock_trigger):
        # Sandbox mode gets real-time events directly (Phase 4), no
        # polling involved, so there is nothing to fast-mode here.
        order_poller_subscriber.on_order_placed(make_event(mode="analyze"))

        mock_trigger.assert_not_called()

    @patch("subscribers.order_poller_subscriber.trigger_fast_mode")
    def test_does_not_trigger_when_api_key_missing(self, mock_trigger):
        order_poller_subscriber.on_order_placed(make_event(mode="live", api_key=""))

        mock_trigger.assert_not_called()

    @patch("subscribers.order_poller_subscriber.get_auth_token_broker")
    @patch("subscribers.order_poller_subscriber.verify_api_key")
    @patch("subscribers.order_poller_subscriber.trigger_fast_mode")
    def test_does_not_trigger_when_api_key_invalid(
        self, mock_trigger, mock_verify, mock_get_broker
    ):
        mock_verify.return_value = None

        order_poller_subscriber.on_order_placed(make_event(mode="live"))

        mock_get_broker.assert_not_called()
        mock_trigger.assert_not_called()

    @patch("subscribers.order_poller_subscriber.get_auth_token_broker")
    @patch("subscribers.order_poller_subscriber.verify_api_key")
    @patch("subscribers.order_poller_subscriber.trigger_fast_mode")
    def test_does_not_trigger_when_broker_unresolved(
        self, mock_trigger, mock_verify, mock_get_broker
    ):
        mock_verify.return_value = "user1"
        mock_get_broker.return_value = (None, None)

        order_poller_subscriber.on_order_placed(make_event(mode="live"))

        mock_trigger.assert_not_called()


class TestOnOrderModified:
    @patch("subscribers.order_poller_subscriber.trigger_fast_mode")
    @patch("subscribers.order_poller_subscriber.get_auth_token_broker")
    @patch("subscribers.order_poller_subscriber.verify_api_key")
    def test_triggers_fast_mode_for_live_modify(self, mock_verify, mock_get_broker, mock_trigger):
        mock_verify.return_value = "user1"
        mock_get_broker.return_value = ("decrypted-token", "dhan")

        order_poller_subscriber.on_order_modified(make_event(mode="live"))

        mock_trigger.assert_called_once_with("dhan", "user1")

    @patch("subscribers.order_poller_subscriber.trigger_fast_mode")
    def test_does_not_trigger_for_analyze_mode(self, mock_trigger):
        order_poller_subscriber.on_order_modified(make_event(mode="analyze"))

        mock_trigger.assert_not_called()


class TestOnOrderCancelled:
    @patch("subscribers.order_poller_subscriber.trigger_fast_mode")
    @patch("subscribers.order_poller_subscriber.get_auth_token_broker")
    @patch("subscribers.order_poller_subscriber.verify_api_key")
    def test_triggers_fast_mode_for_live_cancel(self, mock_verify, mock_get_broker, mock_trigger):
        mock_verify.return_value = "user1"
        mock_get_broker.return_value = ("decrypted-token", "angel")

        order_poller_subscriber.on_order_cancelled(make_event(mode="live"))

        mock_trigger.assert_called_once_with("angel", "user1")

    @patch("subscribers.order_poller_subscriber.trigger_fast_mode")
    def test_does_not_trigger_for_analyze_mode(self, mock_trigger):
        order_poller_subscriber.on_order_cancelled(make_event(mode="analyze"))

        mock_trigger.assert_not_called()
