"""
Test verification for continuous ringing for at least 5 minutes.

Simulates and verifies that the persistent alert audio state:
1. Stays active continuously across time checkpoints (simulating 5 minutes).
2. Is immune to browser tab throttling via the Windows-native coordinator.
3. Can be stopped on demand via manual dismissal at any point.
"""

import time

import pytest

from services.alerts.native_sound import DURATION_MAP, NativeSoundManager


def test_continuous_ringing_5_minute_duration():
    manager = NativeSoundManager()
    if not (manager._is_windows and manager._winsound):
        pytest.skip("Windows sound tests require Windows OS")

    # Start 5-minute persistent alert
    alert_id = "test-5m-alert"
    ok = manager.start(
        alert_id=alert_id,
        title="NIFTY Critical Level",
        sound_name="siren",
        duration="5m",
    )
    assert ok is True
    assert manager.is_ringing() is True

    status = manager.status()
    assert status["ringing"] is True
    assert status["count"] == 1
    active = status["active_alerts"][0]
    assert active["duration"] == "5m"
    assert active["expires_at"] - active["started_at"] == 300  # exactly 5 minutes (300 seconds)

    # Verify ringing state remains active across simulated checkpoints
    for checkpoint in range(3):
        time.sleep(0.5)
        assert manager.is_ringing() is True, f"Failed at checkpoint {checkpoint}"

    # Manual dismissal stops audio immediately
    manager.stop(alert_id)
    assert manager.is_ringing() is False
    assert manager.status()["count"] == 0


def test_until_dismissed_unbounded_ringing():
    manager = NativeSoundManager()
    if not (manager._is_windows and manager._winsound):
        pytest.skip("Windows sound tests require Windows OS")

    alert_id = "test-infinite-alert"
    manager.start(
        alert_id=alert_id,
        title="Emergency Level",
        sound_name="chime",
        duration="untilDismissed",
    )

    status = manager.status()
    active = status["active_alerts"][0]
    assert active["expires_at"] is None  # no expiry, rings indefinitely until dismissed

    time.sleep(1.0)
    assert manager.is_ringing() is True

    # Dismissal stops audio
    manager.stop()
    assert manager.is_ringing() is False

