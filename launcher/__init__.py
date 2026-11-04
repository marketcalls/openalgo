"""The Windows desktop launcher: panel, keeper and reset.

See ``docs/plans/2026-11-05-desktop-panel-and-reset-plan.md``.

Everything in this package uses the Python standard library only and must keep
doing so. It runs on the base Python, not the project's ``.venv``, so the panel
still opens, and the reset still works, when the dependencies are broken. Do not
import from the application (``utils``, ``database``, ``services``) here.
"""
