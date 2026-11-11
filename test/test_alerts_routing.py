"""Order events become alerts, and alerts reach the channels routed to them.

Before this, ``subscribers/telegram_subscriber.py`` and
``subscribers/whatsapp_subscriber.py`` each subscribed to every order topic.
Now one subscriber raises an ``AlertRaisedEvent`` per order event and every
channel receives it on its own bus callback. These tests pin what must not
change for the installs that never open /alerts (the same events still reach
Telegram and WhatsApp, with the same arguments), and what the page adds (a
switch and a per-group route per channel).
"""

from __future__ import annotations

import threading
import time
import types

import pytest
from sqlalchemy.orm import scoped_session, sessionmaker

import database.alert_channels_db as alert_channels_db
from database.engine_factory import create_db_engine
from events import (
    AllOrdersCancelledEvent,
    AnalyzerErrorEvent,
    BasketCompletedEvent,
    GTTFailedEvent,
    GTTTriggeredEvent,
    MultiOrderCompletedEvent,
    OptionsOrderCompletedEvent,
    OrderCancelFailedEvent,
    OrderCancelledEvent,
    OrderFailedEvent,
    OrderModifiedEvent,
    OrderModifyFailedEvent,
    OrderPlacedEvent,
    OrderUpdateEvent,
    PositionClosedEvent,
    SandboxOrderFilledEvent,
    SmartOrderNoActionEvent,
    SplitCompletedEvent,
)
from events.alert_events import ALERT_TOPIC, AlertRaisedEvent
from services.alerts import router, settings
from services.alerts.categories import ALERT_TOPICS, CATEGORY_BY_TOPIC, CATEGORY_IDS
from services.alerts.channels.base import AlertChannel, ChannelStatus, DeliveryResult
from services.alerts.registry import CHANNELS, get_channel
from subscribers import alert_subscriber
from utils.event_bus import EventBus

#: Every topic the removed telegram and whatsapp subscribers sent an alert for.
#: Their failure handlers (order.failed and the like) were empty.
PREVIOUSLY_ALERTED = {
    "order.placed",
    "order.no_action",
    "order.modified",
    "order.cancelled",
    "orders.all_cancelled",
    "position.closed",
    "basket.completed",
    "split.completed",
    "options.completed",
    "multiorder.completed",
    "gtt.placed",
    "gtt.modified",
    "gtt.cancelled",
    "gtt.triggered",
    "gtt.expired",
}


@pytest.fixture
def store(tmp_path, monkeypatch):
    """The alert settings table on a file of its own, and an empty cache."""
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'openalgo.db').as_posix()}")
    session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
    monkeypatch.setattr(alert_channels_db, "engine", engine)
    monkeypatch.setattr(alert_channels_db, "db_session", session)
    previous = alert_channels_db.Base.__dict__["query"]
    alert_channels_db.Base.query = session.query_property()
    alert_channels_db.Base.metadata.create_all(engine)
    settings.clear_cache()
    try:
        yield engine
    finally:
        settings.clear_cache()
        alert_channels_db.Base.query = previous
        session.remove()
        engine.dispose()


class RecordingChannel(AlertChannel):
    """A channel that writes down what it was handed."""

    uses_webhook = False
    enabled_by_default = True

    def __init__(self, name: str, fail: bool = False):
        self.name = name
        self.label = name.title()
        self.setup_path = f"/{name}"
        self.fail = fail
        self.received: list[AlertRaisedEvent] = []
        self.done = threading.Event()

    def status(self) -> ChannelStatus:
        return ChannelStatus(configured=True, ready=True, detail="ok")

    def deliver(self, alert: AlertRaisedEvent) -> None:
        self.received.append(alert)
        self.done.set()
        if self.fail:
            raise RuntimeError("this channel is broken")

    def send_test(self) -> DeliveryResult:
        return DeliveryResult(delivered=True, message="ok")


def _placed(**fields) -> OrderPlacedEvent:
    base = {
        "mode": "live",
        "api_type": "placeorder",
        "request_data": {"symbol": "SBIN", "action": "BUY", "quantity": "1"},
        "response_data": {"status": "success", "orderid": "1"},
        "api_key": "the-api-key",
    }
    base.update(fields)
    return OrderPlacedEvent(**base)


# ---------------------------------------------------------------------------
# What raises an alert
# ---------------------------------------------------------------------------


def test_the_same_topics_raise_an_alert_as_before():
    assert set(ALERT_TOPICS) == PREVIOUSLY_ALERTED


@pytest.mark.parametrize(
    "event",
    [
        OrderFailedEvent(),
        OrderModifyFailedEvent(),
        OrderCancelFailedEvent(),
        AnalyzerErrorEvent(),
        GTTFailedEvent(),
        OrderUpdateEvent(),
        SandboxOrderFilledEvent(),
    ],
    ids=lambda e: e.topic,
)
def test_failures_and_engine_events_raise_no_alert(event):
    assert router.alert_for(event) is None


@pytest.mark.parametrize(
    ("event", "category"),
    [
        (OrderPlacedEvent(), "orders_placed"),
        (SmartOrderNoActionEvent(), "orders_placed"),
        (OrderModifiedEvent(), "orders_modified"),
        (OrderCancelledEvent(), "orders_cancelled"),
        (AllOrdersCancelledEvent(), "orders_cancelled"),
        (PositionClosedEvent(), "positions_closed"),
        (BasketCompletedEvent(), "batch_orders"),
        (SplitCompletedEvent(), "batch_orders"),
        (OptionsOrderCompletedEvent(), "batch_orders"),
        (MultiOrderCompletedEvent(), "batch_orders"),
        (GTTTriggeredEvent(), "gtt_orders"),
    ],
    ids=lambda v: getattr(v, "topic", v),
)
def test_each_alerting_topic_has_its_group(event, category):
    assert router.alert_for(event).category == category


def test_an_alert_carries_the_order_event_unchanged():
    event = _placed(mode="analyze")

    alert = router.alert_for(event)

    assert alert.topic == ALERT_TOPIC
    assert alert.source_topic == "order.placed"
    assert (alert.mode, alert.api_type, alert.api_key) == ("analyze", "placeorder", "the-api-key")
    assert alert.request_data is event.request_data
    assert alert.response_data is event.response_data


# ---------------------------------------------------------------------------
# Who receives it
# ---------------------------------------------------------------------------


def test_with_nothing_saved_telegram_and_whatsapp_receive_every_group(store):
    """An install that never opens /alerts keeps the alerts it had."""
    for name in ("telegram", "whatsapp"):
        current = settings.settings_for(get_channel(name))
        assert current.enabled
        assert current.categories == frozenset(CATEGORY_IDS)


def test_with_nothing_saved_slack_and_discord_receive_nothing(store):
    for name in ("slack", "discord"):
        assert not settings.settings_for(get_channel(name)).enabled


def test_a_channel_switched_off_is_not_handed_the_alert(store):
    channel = RecordingChannel("telegram")
    settings.update_settings(get_channel("telegram"), enabled=False)

    assert not router.deliver(channel, router.alert_for(_placed()))
    assert channel.received == []


def test_a_group_routed_away_from_a_channel_is_not_handed_to_it(store):
    channel = RecordingChannel("telegram")
    settings.update_settings(get_channel("telegram"), categories=["gtt_orders"])

    assert not router.deliver(channel, router.alert_for(_placed()))
    assert router.deliver(channel, router.alert_for(GTTTriggeredEvent(api_type="placegttorder")))
    assert [a.category for a in channel.received] == ["gtt_orders"]


def test_an_unknown_group_is_refused(store):
    with pytest.raises(settings.UnknownCategory):
        settings.update_settings(get_channel("slack"), categories=["orders_placed", "bogus"])


def test_a_change_is_seen_on_the_next_alert(store):
    """The settings cache is cleared by the write, not by waiting for it to expire."""
    telegram = get_channel("telegram")
    assert settings.settings_for(telegram).enabled

    settings.update_settings(telegram, enabled=False)

    assert not settings.settings_for(telegram).enabled


def test_a_settings_table_that_cannot_be_read_does_not_silence_telegram(store, monkeypatch):
    def broken(channel):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(alert_channels_db, "load_channel", broken)

    assert settings.settings_for(get_channel("telegram")).enabled


# ---------------------------------------------------------------------------
# Telegram and WhatsApp still send through their own services
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "module", "attribute"),
    [
        ("telegram", "services.telegram_alert_service", "telegram_alert_service"),
        ("whatsapp", "services.whatsapp_alert_service", "whatsapp_alert_service"),
    ],
)
def test_telegram_and_whatsapp_get_the_arguments_the_old_subscribers_passed(
    name, module, attribute, monkeypatch
):
    import importlib

    service = getattr(importlib.import_module(module), attribute)
    calls = []
    monkeypatch.setattr(service, "send_order_alert", lambda *args: calls.append(args))
    event = _placed()

    get_channel(name).deliver(router.alert_for(event))

    assert calls == [(event.api_type, event.request_data, event.response_data, event.api_key)]


# ---------------------------------------------------------------------------
# On a real event bus
# ---------------------------------------------------------------------------


@pytest.fixture
def wired(store, monkeypatch):
    """A fresh bus with the alert subscriber registered against recording channels."""
    bus = EventBus(workers=4)
    channels = (
        RecordingChannel("telegram", fail=True),
        RecordingChannel("whatsapp"),
        RecordingChannel("slack"),
    )
    monkeypatch.setattr(alert_subscriber, "bus", bus)
    monkeypatch.setattr(alert_subscriber, "CHANNELS", channels)
    monkeypatch.setattr(
        settings,
        "defaults",
        lambda channel: settings.ChannelSettings(enabled=True, categories=frozenset(CATEGORY_IDS)),
    )
    alert_subscriber.register()
    return types.SimpleNamespace(bus=bus, channels=channels)


def _drain(bus, timeout: float = 5.0) -> None:
    """Wait until the bus has run every callback it was handed.

    Counting after the first delivery would race a duplicate arriving later.
    ``raise_alert`` publishes before its own slot is released, so the count
    never touches zero between an order event and its alert.
    """
    deadline = time.monotonic() + timeout
    while bus.stats()["pending"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert bus.stats()["pending"] == 0, "the bus did not drain"


def test_one_order_event_reaches_every_channel_exactly_once(wired):
    wired.bus.publish(_placed())
    _drain(wired.bus)

    assert [len(channel.received) for channel in wired.channels] == [1, 1, 1]
    assert {channel.received[0].category for channel in wired.channels} == {"orders_placed"}


def test_a_failing_channel_does_not_stop_the_others(wired):
    """telegram raises on every delivery; whatsapp and slack still get the alert."""
    wired.bus.publish(_placed())
    _drain(wired.bus)

    assert wired.channels[1].received and wired.channels[2].received


def test_a_failure_event_reaches_no_channel(wired):
    wired.bus.publish(OrderFailedEvent(api_type="placeorder"))
    _drain(wired.bus)

    assert all(channel.received == [] for channel in wired.channels)


def test_no_alert_is_published_when_no_channel_wants_it(wired, monkeypatch):
    """An alert nobody receives must not take a bus slot."""
    published = []
    wired.bus.subscribe(ALERT_TOPIC, published.append, "spy")
    monkeypatch.setattr(
        settings,
        "defaults",
        lambda channel: settings.ChannelSettings(enabled=False, categories=frozenset(CATEGORY_IDS)),
    )

    wired.bus.publish(_placed())
    _drain(wired.bus)

    assert published == []
    assert all(channel.received == [] for channel in wired.channels)


def test_an_order_event_costs_the_bus_two_alert_callbacks(monkeypatch):
    """One to raise the alert and one to deliver it, as the two removed
    Telegram and WhatsApp subscribers took; not one per channel."""
    bus = EventBus(workers=1)
    monkeypatch.setattr(alert_subscriber, "bus", bus)

    alert_subscriber.register()

    assert [s.name for s in bus._subscribers[ALERT_TOPIC]] == ["alerts:deliver"]
    for topic in ALERT_TOPICS:
        assert [s.name for s in bus._subscribers[topic]] == [f"alerts:raise:{topic}"]
    assert set(bus._subscribers) == set(ALERT_TOPICS) | {ALERT_TOPIC}
    assert set(CATEGORY_BY_TOPIC) == set(ALERT_TOPICS)
    assert len(CHANNELS) == 4
