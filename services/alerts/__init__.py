"""Alerts: telling a trader, on the channels they chose, what their orders did.

How an alert travels, end to end, all on the event bus:

1. An order service publishes an order event (``order.placed`` and so on).
2. ``subscribers/alert_subscriber.py`` maps it to an alert group
   (``categories.py``) and, when at least one channel receives that group,
   publishes one ``AlertRaisedEvent``.
3. One delivery subscriber hands the alert to every channel in
   ``registry.py`` that is switched on and receives the group
   (``router.receivers``, ``settings.py``), each in its own ``try``.
4. The channel formats and queues it without waiting on the network:
   Telegram and WhatsApp through their existing services and their own
   alert pools, Slack and Discord on their own webhook lanes
   (``channels/``). Slack, Discord and WhatsApp share one formatter
   (``formatting.py``).

The /alerts page (``blueprints/alert_channels.py``) reads and changes the
same settings, and the ``/api/v1/slack`` and ``/api/v1/discord`` notify
endpoints send through the same channel objects.
"""
