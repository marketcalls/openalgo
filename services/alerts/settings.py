"""Each channel's switch and event routing, as the /alerts page sets them.

Read on every alert, for every channel, so reads are cached and a write clears
the cache once it has committed. A channel nobody has changed uses its
defaults: on for Telegram and WhatsApp with every event group, exactly as they
behaved before this page existed, and off for a webhook channel until its
webhook is saved.

**Writes are serialised per channel and read the stored row.** A change reads
what is saved, applies one field, and writes the whole row back. Two changes
to one channel at once (the switch and a group, from two tabs) would otherwise
each write back what they read, and the later one would undo the earlier. And
a change must never start from the defaults because the row could not be read:
that would quietly switch a channel the trader turned off back on.
"""

from __future__ import annotations

from dataclasses import dataclass

from database import alert_channels_db
from services.alerts.categories import CATEGORY_IDS
from services.alerts.channels.base import AlertChannel
from utils.keyed_locks import KeyedLocks
from utils.logging import get_logger
from utils.thread_safe_cache import MISSING, LockedTTLCache

logger = get_logger(__name__)

#: Settings change only when the trader saves them, and a save clears its
#: entry, so the time limit only bounds how long a write made outside this
#: module (a migration, a restore) can go unseen.
_cache = LockedTTLCache(maxsize=16, ttl=300)

#: One writer per channel at a time. Green under eventlet, real under gthread;
#: the holder does database work, which keyed_locks allows.
_writers = KeyedLocks(name="alert channel settings")

#: How long a change waits for another change to the same channel to finish.
WRITE_WAIT_SECONDS = 10.0


@dataclass(frozen=True)
class ChannelSettings:
    """A channel's switch and the event groups it receives.

    Attributes:
        enabled: Whether the channel is on.
        categories: The event groups it receives.
    """

    enabled: bool
    categories: frozenset[str]

    def receives(self, category: str) -> bool:
        """Whether an alert in ``category`` goes to this channel."""
        return self.enabled and category in self.categories


class UnknownCategory(ValueError):
    """An event group that does not exist. The message is for the trader."""


class WebhookRequired(ValueError):
    """A webhook channel switched on with no usable webhook. For the trader."""


def defaults(channel: AlertChannel) -> ChannelSettings:
    """What a channel does before anybody changes it."""
    return ChannelSettings(enabled=channel.enabled_by_default, categories=frozenset(CATEGORY_IDS))


def settings_for(channel: AlertChannel) -> ChannelSettings:
    """A channel's current settings.

    A database that cannot be read falls back to the defaults, so a broken
    settings table never silences Telegram or WhatsApp, which were always on.
    """
    cached = _cache.get(channel.name, MISSING)
    if cached is not MISSING:
        return cached
    generation = _cache.generation
    try:
        stored = alert_channels_db.load_channel(channel.name)
    except Exception:
        logger.exception(f"Could not read the {channel.label} alert settings; using defaults")
        return defaults(channel)
    settings = _from_stored(channel, stored)
    _cache.fill(channel.name, settings, generation)
    return settings


def _from_stored(channel: AlertChannel, stored) -> ChannelSettings:
    """Settings from a stored row, or the defaults when there is none."""
    if stored is None:
        return defaults(channel)
    return ChannelSettings(
        enabled=stored.enabled,
        # A group that no longer exists is ignored rather than an error.
        categories=frozenset(stored.categories) & frozenset(CATEGORY_IDS),
    )


def update_settings(
    channel: AlertChannel,
    *,
    enabled: bool | None = None,
    categories: list[str] | None = None,
) -> ChannelSettings:
    """Change a channel's switch, its event groups, or both.

    Args:
        channel: The channel to change.
        enabled: Turn it on or off. None keeps it as it is.
        categories: The event groups it should receive. None keeps them.

    Returns:
        The settings now in force.

    Raises:
        UnknownCategory: ``categories`` names a group that does not exist.
        WebhookRequired: A webhook channel switched on with no usable webhook.
        LockBusy: Another change to this channel did not finish in time.
        Exception: The stored settings could not be read or written. Nothing
            is changed.
    """
    if categories is not None:
        unknown = sorted(set(categories) - set(CATEGORY_IDS))
        if unknown:
            raise UnknownCategory(f"Unknown event group: {', '.join(unknown)}")
    with _writers.hold(channel.name, timeout=WRITE_WAIT_SECONDS):
        # Checked under the lock that forget_webhook takes, so a webhook
        # removed at the same moment cannot leave the channel on without one.
        if enabled and channel.uses_webhook and not channel.status().configured:
            raise WebhookRequired(
                f"Save a {channel.label} webhook before turning {channel.label} on."
            )
        # The row itself, not the cached read: a read that fails raises here
        # instead of handing back the defaults.
        current = _from_stored(channel, alert_channels_db.load_channel(channel.name))
        updated = ChannelSettings(
            enabled=current.enabled if enabled is None else enabled,
            categories=current.categories if categories is None else frozenset(categories),
        )
        alert_channels_db.save_channel(
            channel.name,
            enabled=updated.enabled,
            categories=tuple(c for c in CATEGORY_IDS if c in updated.categories),
        )
        _cache.invalidate(channel.name)
    return updated


def save_webhook(channel: AlertChannel, url: str) -> ChannelSettings:
    """Store a validated webhook URL and turn the channel on.

    Saving a webhook is what turning a webhook channel on means to a trader,
    so it is switched on here rather than leaving a second step to forget.
    """
    with _writers.hold(channel.name, timeout=WRITE_WAIT_SECONDS):
        alert_channels_db.save_webhook(
            channel.name, url, enabled=True, default_categories=CATEGORY_IDS
        )
        _cache.invalidate(channel.name)
    return settings_for(channel)


def forget_webhook(channel: AlertChannel) -> ChannelSettings:
    """Remove a webhook URL. The channel is turned off with it."""
    with _writers.hold(channel.name, timeout=WRITE_WAIT_SECONDS):
        alert_channels_db.clear_webhook(channel.name)
        _cache.invalidate(channel.name)
    return settings_for(channel)


def clear_cache() -> None:
    """Forget every cached setting. For tests."""
    _cache.invalidate()
