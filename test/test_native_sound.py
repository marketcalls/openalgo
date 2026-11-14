import time

import pytest

from services.alerts.native_sound import DURATION_MAP, WINDOWS_SOUND_MAP, NativeSoundManager


def test_native_sound_durations():
    assert DURATION_MAP["once"] == 0
    assert DURATION_MAP["3s"] == 3
    assert DURATION_MAP["5s"] == 5
    assert DURATION_MAP["10s"] == 10
    assert DURATION_MAP["30s"] == 30
    assert DURATION_MAP["1m"] == 60
    assert DURATION_MAP["5m"] == 300
    assert DURATION_MAP["untilDismissed"] is None


def test_native_sound_lifecycle():
    manager = NativeSoundManager()

    # Start persistent ringing
    ok = manager.start("test-alert-1", title="Test Alert", sound_name="chime", duration="untilDismissed")
    if manager._is_windows and manager._winsound:
        assert ok is True
        assert manager.is_ringing() is True
        st = manager.status()
        assert st["ringing"] is True
        assert st["count"] == 1

        # Stop ringing
        manager.stop("test-alert-1")
        assert manager.is_ringing() is False
        assert manager.status()["count"] == 0


def test_native_sound_timed_expiration():
    manager = NativeSoundManager()
    if not (manager._is_windows and manager._winsound):
        pytest.skip("Not on Windows or winsound unavailable")

    # Start with 3s duration
    manager.start("short-alert", title="Expiring Alert", sound_name="beep", duration="3s")
    assert manager.is_ringing() is True

    # Wait for expiration
    time.sleep(3.5)
    assert manager.is_ringing() is False


def test_native_sound_duplicate_prevention():
    manager = NativeSoundManager()
    if not (manager._is_windows and manager._winsound):
        pytest.skip("Not on Windows or winsound unavailable")

    manager.start("dup-alert", title="Dup 1", sound_name="radar", duration="untilDismissed")
    manager.start("dup-alert", title="Dup 1", sound_name="radar", duration="untilDismissed")
    assert manager.status()["count"] == 1
    manager.stop()
    assert manager.is_ringing() is False

