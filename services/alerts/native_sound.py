"""
Native Windows Alert Sound & Continuous Ringing Coordinator.

Provides persistent audio playback via Windows Multimedia services (winsound),
ensuring uninterrupted alerts when the browser is minimized, sleeping,
or another application is in focus.
"""

import os
import platform
import sys
import threading
import time
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)

# Standard Windows sound assets
WINDOWS_SOUND_MAP = {
    "chime": r"C:\Windows\Media\chimes.wav",
    "siren": r"C:\Windows\Media\Alarm02.wav",
    "radar": r"C:\Windows\Media\Ring01.wav",
    "beep": r"C:\Windows\Media\notify.wav",
    "synth": r"C:\Windows\Media\Alarm01.wav",
}

DURATION_MAP = {
    "once": 0,
    "3s": 3,
    "5s": 5,
    "10s": 10,
    "30s": 30,
    "1m": 60,
    "5m": 300,
    "untilDismissed": None,
}


class NativeSoundManager:
    """Coordinates Windows-native alert sound playback across operating states."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active_alerts: dict[str, dict[str, Any]] = {}
        self._stop_event = threading.Event()
        self._loop_thread: threading.Thread | None = None
        self._is_windows = platform.system().lower() == "windows"
        self._winsound = None

        if self._is_windows:
            try:
                import winsound
                self._winsound = winsound
            except ImportError:
                logger.warning("winsound module not available on this platform")

    def _resolve_sound_file(self, sound_name: str) -> str | None:
        target = WINDOWS_SOUND_MAP.get(sound_name, WINDOWS_SOUND_MAP["chime"])
        if os.path.exists(target):
            return target
        # Fallback to any available wav
        for path in WINDOWS_SOUND_MAP.values():
            if os.path.exists(path):
                return path
        return None

    def start(
        self,
        alert_id: str,
        title: str = "Alert",
        sound_name: str = "chime",
        duration: str = "once",
        volume: float = 0.8,
    ) -> bool:
        """
        Trigger native alert playback.
        duration: 'once', '3s', '5s', '10s', '30s', '1m', '5m', or 'untilDismissed'
        """
        if not self._is_windows or not self._winsound:
            return False

        duration_sec = DURATION_MAP.get(duration, 0)
        sound_file = self._resolve_sound_file(sound_name)

        with self._lock:
            # If duration is 'once', play single asynchronous sound
            if duration == "once" or duration_sec == 0:
                try:
                    if sound_file:
                        self._winsound.PlaySound(
                            sound_file,
                            self._winsound.SND_FILENAME | self._winsound.SND_ASYNC,
                        )
                    else:
                        self._winsound.MessageBeep(self._winsound.MB_ICONEXCLAMATION)
                    return True
                except Exception as exc:
                    logger.warning(f"Failed to play one-shot sound: {exc}")
                    return False

            # Persistent ringing:
            now = time.time()
            self._active_alerts[alert_id] = {
                "id": alert_id,
                "title": title,
                "sound_name": sound_name,
                "duration": duration,
                "started_at": now,
                "expires_at": (now + duration_sec) if duration_sec else None,
                "file": sound_file,
            }

            # If loop is already running, active alert is registered and will be maintained
            if self._loop_thread and self._loop_thread.is_alive():
                return True

            self._stop_event.clear()
            self._loop_thread = threading.Thread(
                target=self._run_loop,
                args=(sound_file,),
                daemon=True,
                name="NativeSoundLoopThread",
            )
            self._loop_thread.start()
            return True

    def _run_loop(self, sound_file: str | None):
        """Maintains looping audio in background until dismissed or expired."""
        try:
            # Play continuous looping asynchronous sound
            if sound_file and self._winsound:
                try:
                    self._winsound.PlaySound(
                        sound_file,
                        self._winsound.SND_FILENAME
                        | self._winsound.SND_ASYNC
                        | self._winsound.SND_LOOP,
                    )
                except Exception as exc:
                    logger.warning(f"PlaySound loop error: {exc}")

            while not self._stop_event.is_set():
                time.sleep(0.5)
                with self._lock:
                    now = time.time()
                    expired = [
                        aid
                        for aid, data in self._active_alerts.items()
                        if data.get("expires_at") and now >= data["expires_at"]
                    ]
                    for aid in expired:
                        self._active_alerts.pop(aid, None)

                    if not self._active_alerts:
                        break
        finally:
            self._silence()

    def _silence(self):
        """Immediately stops all Windows audio output."""
        if self._winsound:
            try:
                self._winsound.PlaySound(None, self._winsound.SND_PURGE)
            except Exception:
                pass

    def stop(self, alert_id: str | None = None) -> bool:
        """
        Stop persistent sound.
        If alert_id is provided, removes that alert.
        If no alerts remain or alert_id is None, immediately silences all audio.
        """
        with self._lock:
            if alert_id is None:
                self._active_alerts.clear()
            else:
                self._active_alerts.pop(alert_id, None)

            if not self._active_alerts:
                self._stop_event.set()
                self._silence()
        return True

    def is_ringing(self) -> bool:
        with self._lock:
            return bool(self._active_alerts)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ringing": bool(self._active_alerts),
                "count": len(self._active_alerts),
                "active_alerts": list(self._active_alerts.values()),
            }


native_sound_manager = NativeSoundManager()

