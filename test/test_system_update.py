"""Tests for the System Update blueprint helpers (version + safety guards).

The routes themselves are thin wrappers around these helpers and are exercised
by the running app; keeping the network and clock out of the unit tests means
they stay offline-safe in CI.
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from blueprints import system_update as su

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture(autouse=True)
def clear_behind_cache():
    """Each test starts with an empty compare cache."""
    su._BEHIND_CACHE.clear()
    yield
    su._BEHIND_CACHE.clear()


class TestSlugFromRemote:
    def test_https_remote(self):
        assert (
            su._slug_from_remote("https://github.com/nihal697/openalgo.git") == "nihal697/openalgo"
        )

    def test_https_remote_without_git_suffix(self):
        assert su._slug_from_remote("https://github.com/owner/repo") == "owner/repo"

    def test_ssh_remote(self):
        assert su._slug_from_remote("git@github.com:owner/repo.git") == "owner/repo"

    @pytest.mark.parametrize("remote", ["", None, "unknown", "https://gitlab.com/owner/repo.git"])
    def test_non_github_or_missing_remote(self, remote):
        assert su._slug_from_remote(remote) is None


class TestInMarketHours:
    def test_open_is_guarded(self):
        assert su._in_market_hours(datetime(2026, 1, 5, 9, 0, tzinfo=IST)) is True

    def test_close_is_guarded(self):
        assert su._in_market_hours(datetime(2026, 1, 5, 15, 30, tzinfo=IST)) is True

    def test_before_open_is_allowed(self):
        assert su._in_market_hours(datetime(2026, 1, 5, 8, 59, tzinfo=IST)) is False

    def test_after_close_is_allowed(self):
        assert su._in_market_hours(datetime(2026, 1, 5, 15, 31, tzinfo=IST)) is False

    def test_naive_datetime_is_read_as_ist(self):
        assert su._in_market_hours(datetime(2026, 1, 5, 12, 0)) is True


class TestBakedStamps:
    def test_read_stamp(self, tmp_path):
        stamp = tmp_path / "BUILD_SHA"
        stamp.write_text("e9d843c33\n")
        assert su._read_stamp(stamp) == "e9d843c33"

    def test_read_stamp_missing_file(self, tmp_path):
        assert su._read_stamp(tmp_path / "nope") == "unknown"

    def test_read_json(self, tmp_path):
        result = tmp_path / "update_result.json"
        result.write_text(json.dumps({"state": "done"}))
        assert su._read_json(result) == {"state": "done"}

    def test_read_json_malformed(self, tmp_path):
        broken = tmp_path / "update_result.json"
        broken.write_text("{not json")
        assert su._read_json(broken) is None


class TestBehindCache:
    def test_hits_github_once_per_ttl(self, monkeypatch):
        calls = []

        def fake_behind(slug, sha, branch, timeout=8):
            calls.append((slug, sha, branch))
            return 4

        monkeypatch.setattr(su, "_github_behind", fake_behind)

        assert su._behind_cached("owner/repo", "abc1234", "main") == 4
        assert su._behind_cached("owner/repo", "abc1234", "main") == 4
        assert calls == [("owner/repo", "abc1234", "main")]

    def test_new_sha_refetches_and_drops_stale_entries(self, monkeypatch):
        monkeypatch.setattr(su, "_github_behind", lambda *a, **k: 1)

        su._behind_cached("owner/repo", "oldsha", "main")
        su._behind_cached("owner/repo", "newsha", "main")

        assert list(su._BEHIND_CACHE) == [("owner/repo", "newsha", "main")]

    def test_failure_is_cached_as_unknown(self, monkeypatch):
        calls = []

        def failing(slug, sha, branch, timeout=8):
            calls.append(1)
            return -1

        monkeypatch.setattr(su, "_github_behind", failing)

        assert su._behind_cached("owner/repo", "abc1234", "main") == -1
        assert su._behind_cached("owner/repo", "abc1234", "main") == -1
        assert len(calls) == 1


class TestGithubBehind:
    @pytest.mark.parametrize("slug,sha", [(None, "abc1234"), ("owner/repo", "unknown"), ("", "")])
    def test_missing_inputs_skip_the_network(self, monkeypatch, slug, sha):
        def boom(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("network call attempted")

        monkeypatch.setattr("urllib.request.urlopen", boom)
        assert su._github_behind(slug, sha, "main") == -1

    def test_parses_behind_by(self, monkeypatch):
        payload = json.dumps({"behind_by": 7, "status": "diverged"}).encode()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return payload

        monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: FakeResponse())
        assert su._github_behind("owner/repo", "abc1234", "main") == 7

    def test_network_error_is_unknown(self, monkeypatch):
        def offline(*args, **kwargs):
            raise OSError("no route to host")

        monkeypatch.setattr("urllib.request.urlopen", offline)
        assert su._github_behind("owner/repo", "abc1234", "main") == -1


class TestClaimExclusive:
    def test_first_caller_wins_and_content_is_kept(self, tmp_path):
        lock = tmp_path / "lock"
        assert su._claim_exclusive(lock, "first") is True
        assert su._claim_exclusive(lock, "second") is False
        assert lock.read_text() == "first"

    def test_any_oserror_counts_as_taken(self, tmp_path):
        # A directory at the path makes os.open fail — must not crash or claim.
        blocker = tmp_path / "blocked"
        blocker.mkdir()
        assert su._claim_exclusive(blocker, "x") is False


class TestLaunchDetached:
    def _capture(self, monkeypatch, tmp_path):
        calls = {}

        class FakePopen:
            def __init__(self, argv, **kwargs):
                calls["argv"] = argv
                calls["env"] = kwargs.get("env")
                calls["cwd"] = kwargs.get("cwd")

        monkeypatch.setattr(su.subprocess, "Popen", FakePopen)
        monkeypatch.setattr(su, "WRAPPER", tmp_path / "no-wrapper-here")
        return calls

    def test_force_is_passed_to_the_child(self, monkeypatch, tmp_path):
        calls = self._capture(monkeypatch, tmp_path)
        su._launch_update_detached(str(tmp_path), "local", force=True)
        assert calls["env"]["WEB_UPDATE_FORCE"] == "1"

    def test_no_force_no_env_override(self, monkeypatch, tmp_path):
        calls = self._capture(monkeypatch, tmp_path)
        su._launch_update_detached(str(tmp_path), "local", force=False)
        assert "WEB_UPDATE_FORCE" not in calls["env"]

    def test_local_runs_without_sudo(self, monkeypatch, tmp_path):
        calls = self._capture(monkeypatch, tmp_path)
        su._launch_update_detached(str(tmp_path), "local")
        assert calls["argv"][:2] == ["/bin/bash", str(tmp_path / "install" / "update_web.sh")]

    def test_server_without_wrapper_uses_sudo(self, monkeypatch, tmp_path):
        calls = self._capture(monkeypatch, tmp_path)
        su._launch_update_detached(str(tmp_path), "server")
        assert calls["argv"][0] == "sudo"

    def test_root_owned_wrapper_is_preferred(self, monkeypatch, tmp_path):
        calls = self._capture(monkeypatch, tmp_path)
        wrapper = tmp_path / "openalgo-update"
        wrapper.write_text("#!/bin/bash\n")
        monkeypatch.setattr(su, "WRAPPER", wrapper)
        su._launch_update_detached(str(tmp_path), "server")
        assert calls["argv"] == ["sudo", "/bin/bash", str(wrapper), str(tmp_path)]
