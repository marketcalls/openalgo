"""Alerts: telling a trader, on the channels they chose, what their orders did.

How an alert travels, end to end, all on the event bus:

1. An order service publishes an order event (``order.placed`` and so on).
2. ``subscribers/alert_subscriber.py`` maps it to an alert group
   (``categories.py``) and publishes one ``AlertRaisedEvent``.
3. Every channel in ``registry.py`` receives that event as its own bus
   callback. ``router.deliver`` checks the channel's switch and routing
   (``settings.py``) and hands the alert to the channel.
4. The channel formats and sends it: Telegram and WhatsApp through their
   existing services, Slack and Discord by posting to their webhook
   (``channels/``). Slack, Discord and WhatsApp share one formatter
   (``formatting.py``).

The /alerts page (``blueprints/alert_channels.py``) reads and changes the
same settings, and the ``/api/v1/slack`` and ``/api/v1/discord`` notify
endpoints send through the same channel objects.
"""
