"""The agent's OpenScript save tool, and the store it shares with the /trading route.

The point of the shared store is that there is one write sequence. These tests
pin that both callers really go through it, that the tool keeps the store's
rules (name, size, backup, a stale program removed), and that its result never
lets the model say a script compiled when nothing here can compile one.

Every test points the store and the blueprint at a temporary folder; nothing is
written under the real strategies/ directory.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("agno.tools", reason="the agent module needs agno")

from agno.exceptions import RetryAgentRun  # noqa: E402
from flask import Flask  # noqa: E402

import blueprints.openscript as openscript  # noqa: E402
import utils.session  # noqa: E402
from services import openscript_store  # noqa: E402
from services.agent.tools import (  # noqa: E402
    SURFACE_CHART,
    SURFACE_CHAT,
    SURFACE_VOICE,
    ToolContext,
    select_specs,
)
from services.agent.tools.base import OpenAlgoToolkit  # noqa: E402
from services.agent.tools.openscript_gen import OpenScriptToolkit  # noqa: E402

SOURCE = 'version 1\nstudy("Range", overlay = true)\nplot(close, "C", aqua)\n'


def _payload(block: str) -> dict:
    lines = block.strip().splitlines()
    return json.loads("\n".join(lines[1:-1]))


@pytest.fixture
def folder(tmp_path, monkeypatch):
    """Point the store, and so the blueprint that reads it, at a temporary folder."""
    directory = tmp_path / "strategies" / "openscript"
    monkeypatch.setattr(openscript_store, "SCRIPTS_DIR", directory)
    return directory


@pytest.fixture
def audits(monkeypatch):
    """Capture audit rows instead of writing them to the agent database."""
    rows: list[dict] = []

    def record(self, phase, **row):
        rows.append({"phase": phase, **row})
        return None

    monkeypatch.setattr(OpenAlgoToolkit, "_write_audit", record)
    return rows


@pytest.fixture
def toolkit(folder, audits):
    return OpenScriptToolkit(ToolContext(api_key="k", surface=SURFACE_CHAT, conversation_id=0))


@pytest.fixture
def client(folder, monkeypatch):
    monkeypatch.setattr(utils.session, "is_session_valid", lambda: True)
    application = Flask(__name__)
    application.config["TESTING"] = True
    application.secret_key = "test-only"
    application.register_blueprint(openscript.openscript_bp)
    return application.test_client()


def _program_for(source: str) -> str:
    return json.dumps({"source": {"hash": openscript_store.source_hash(source)}})


# ---------------------------------------------------------------------------
# One store, two callers
# ---------------------------------------------------------------------------


class TestOneStore:
    def test_the_route_and_the_tool_both_write_through_the_store(
        self, folder, toolkit, client, monkeypatch
    ):
        calls: list[tuple[str, bool]] = []
        real = openscript_store.write_script

        def spy(directory, filename, source, program=None, **flags):
            calls.append((filename, program is not None))
            return real(directory, filename, source, program, **flags)

        monkeypatch.setattr(openscript_store, "write_script", spy)
        assert client.post("/openscript/a.oscript", json={"source": SOURCE}).status_code == 200
        toolkit.save_openscript("b", SOURCE)
        assert calls == [("a.oscript", False), ("b.oscript", False)]

    def test_the_blueprint_names_are_the_store_objects(self):
        assert openscript._SAFE_NAME is openscript_store.SAFE_NAME
        assert openscript._FILE_LOCKS is openscript_store.FILE_LOCKS
        assert openscript._source_hash is openscript_store.source_hash
        assert openscript._program_path is openscript_store.program_path
        assert openscript._stage is openscript_store.stage
        assert openscript.MAX_SOURCE_BYTES == openscript_store.MAX_SOURCE_BYTES
        assert openscript._PROGRAM_SUFFIX == openscript_store.PROGRAM_SUFFIX

    @pytest.mark.parametrize("replace", [False, True])
    def test_a_tool_save_never_replaces_a_script_the_route_compiled(
        self, folder, toolkit, client, audits, replace
    ):
        # A compiled program is what a deployed strategy starts from. Saving
        # source over it would delete it and refuse the next scheduled start.
        program = _program_for(SOURCE)
        saved = client.post(
            "/openscript/range.oscript", json={"source": SOURCE, "program": program}
        )
        assert saved.status_code == 200 and saved.get_json()["program"] is True

        edited = SOURCE.replace("close", "open")
        with pytest.raises(RetryAgentRun, match="compiled") as refused:
            toolkit.save_openscript("range.oscript", edited, replace=replace)

        assert "/trading" in str(refused.value) and "new name" in str(refused.value)
        assert (folder / "range.oscript.program.json").read_text(encoding="utf-8") == program
        assert (folder / "range.oscript").read_text(encoding="utf-8") == SOURCE
        assert not (folder / "range.oscript.bak").exists()
        assert audits[-1]["phase"] == "result" and audits[-1]["ok"] is False

    def test_the_route_lists_what_the_tool_saved(self, folder, toolkit, client):
        toolkit.save_openscript("listed", SOURCE)
        listing = client.get("/openscript/index.json").get_json()
        assert [entry["file"] for entry in listing] == ["listed.oscript"]
        assert listing[0]["program"] is False


# ---------------------------------------------------------------------------
# The tool
# ---------------------------------------------------------------------------


class TestSave:
    def test_a_new_script_is_written_as_source_and_says_it_is_not_compiled(
        self, folder, toolkit, audits
    ):
        result = _payload(toolkit.save_openscript("ema_cross", SOURCE))
        assert result["ok"] is True and result["saved"] is True
        assert result["file"] == "ema_cross.oscript"
        assert result["compiled"] is False
        assert result["replaced"] is False and result["backup"] is None
        assert result["lines"] == 3
        assert "/trading" in result["next_step"] and "ema_cross.oscript" in result["next_step"]
        assert (folder / "ema_cross.oscript").read_bytes() == SOURCE.encode("utf-8")
        assert not (folder / "ema_cross.oscript.program.json").exists()
        assert [row["phase"] for row in audits] == ["attempt", "result"]
        assert audits[-1]["ok"] is True

    def test_a_taken_name_is_refused_without_replace(self, folder, toolkit, audits):
        toolkit.save_openscript("taken", SOURCE)
        edited = SOURCE.replace("close", "open")

        with pytest.raises(RetryAgentRun, match="already exists") as refused:
            toolkit.save_openscript("taken", edited)

        assert "replace=true" in str(refused.value)
        assert (folder / "taken.oscript").read_text(encoding="utf-8") == SOURCE
        assert not (folder / "taken.oscript.bak").exists()
        assert audits[-1]["phase"] == "result" and audits[-1]["ok"] is False

    def test_replace_true_replaces_a_source_with_no_program(self, folder, toolkit):
        toolkit.save_openscript("draft", SOURCE)
        edited = SOURCE.replace("close", "open")

        result = _payload(toolkit.save_openscript("draft", edited, replace=True))

        assert result["ok"] is True and result["replaced"] is True
        assert result["backup"] == "draft.oscript.bak"
        assert (folder / "draft.oscript").read_text(encoding="utf-8") == edited
        assert (folder / "draft.oscript.bak").read_text(encoding="utf-8") == SOURCE

    def test_replace_true_on_a_new_name_simply_saves(self, folder, toolkit):
        result = _payload(toolkit.save_openscript("fresh", SOURCE, replace=True))
        assert result["ok"] is True and result["replaced"] is False

    def test_the_schema_tells_the_model_about_replace(self, toolkit):
        doc = toolkit.save_openscript.__doc__
        assert "replace=true" in doc and "compiled" in doc and "new name" in doc

    def test_a_fence_around_the_whole_source_is_removed(self, folder, toolkit):
        toolkit.save_openscript("fenced", f"```openscript\n{SOURCE}```")
        assert (folder / "fenced.oscript").read_text(encoding="utf-8") == SOURCE.strip()

    @pytest.mark.parametrize(
        "name", ["", "   ", "../escape", "a/b", ".hidden", "x" * 70, "bad name", "C:evil"]
    )
    def test_a_name_the_store_would_refuse_is_refused_here(self, folder, toolkit, name):
        with pytest.raises(RetryAgentRun, match="filename"):
            toolkit.save_openscript(name, SOURCE)
        assert not folder.exists() or not any(folder.iterdir())

    def test_an_empty_or_oversized_source_is_refused(self, folder, toolkit):
        with pytest.raises(RetryAgentRun, match="source"):
            toolkit.save_openscript("empty", "  \n ")
        too_big = "x" * (openscript_store.MAX_SOURCE_BYTES + 1)
        with pytest.raises(RetryAgentRun, match=str(openscript_store.MAX_SOURCE_BYTES)):
            toolkit.save_openscript("big", too_big)

    def test_a_write_failure_is_reported_in_plain_words(self, folder, toolkit, monkeypatch, audits):
        def refuse(*_args, **_kwargs):
            raise PermissionError("denied")

        monkeypatch.setattr(openscript_store, "write_script", refuse)
        result = _payload(toolkit.save_openscript("nope", SOURCE))
        assert result["ok"] is False and result["saved"] is False
        assert "Errno" not in result["error"] and "PermissionError" not in result["error"]
        assert audits[-1]["ok"] is False

    def test_saving_pauses_for_approval_and_listing_does_not(self, toolkit):
        assert list(toolkit.requires_confirmation_tools) == ["save_openscript"]


class TestList:
    def test_it_lists_names_and_whether_each_is_compiled(self, folder, toolkit, client):
        client.post(
            "/openscript/built.oscript", json={"source": SOURCE, "program": _program_for(SOURCE)}
        )
        toolkit.save_openscript("draft", SOURCE)
        result = _payload(toolkit.list_openscripts())
        assert result["ok"] is True
        compiled = {entry["file"]: entry["compiled"] for entry in result["scripts"]}
        assert compiled == {"built.oscript": True, "draft.oscript": False}
        assert all("+05:30" in entry["modified"] for entry in result["scripts"])

    def test_a_missing_folder_lists_nothing(self, folder, toolkit):
        result = _payload(toolkit.list_openscripts())
        assert result["ok"] is True and result["scripts"] == []


class TestRegistration:
    @pytest.mark.parametrize(
        ("surface", "offered"),
        [(SURFACE_CHAT, True), (SURFACE_CHART, True), (SURFACE_VOICE, False)],
    )
    def test_offered_on_chat_and_chart_not_voice(self, surface, offered):
        keys = {spec.key for spec in select_specs(ToolContext(api_key="k", surface=surface))}
        assert ("openscript_gen" in keys) is offered
        assert ("skills" in keys) is offered

    def test_the_store_never_defaults_into_a_test_folder(self):
        # The fixtures patch it; the shipped value is the real relative path.
        assert openscript_store.SCRIPTS_DIR == Path("strategies") / "openscript"


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


class TestStore:
    def test_exactly_one_leading_byte_order_mark_is_stripped(self):
        mark = chr(0xFEFF)
        assert openscript_store.normalised(mark + "plot(close)\r\n") == "plot(close)\n"
        assert openscript_store.normalised(mark + mark + "x") == mark + "x"
        assert openscript_store.normalised("plot(close)") == "plot(close)"
        assert openscript_store.normalised("") == ""
        assert openscript_store.source_hash(mark + SOURCE) == openscript_store.source_hash(SOURCE)

    def test_the_mark_is_spelled_as_an_escape(self):
        # A raw mark inside the literal is invisible, and an editor that strips
        # it turns the check into startswith(""), which changes every hash.
        source = Path(openscript_store.__file__).read_bytes()
        assert b"\xef\xbb\xbf" not in source
        assert b'startswith("\ufeff")' in source

    def test_the_route_still_replaces_a_compiled_script(self, folder, client):
        # The flags are the agent's; the /trading editor's save is unchanged.
        program = _program_for(SOURCE)
        client.post("/openscript/kept.oscript", json={"source": SOURCE, "program": program})
        edited = SOURCE.replace("close", "open")
        response = client.post(
            "/openscript/kept.oscript", json={"source": edited, "program": _program_for(edited)}
        )
        assert response.status_code == 200
        assert (folder / "kept.oscript").read_text(encoding="utf-8") == edited

    def test_a_refused_write_leaves_nothing_behind(self, folder):
        folder.mkdir(parents=True)
        (folder / "a.oscript").write_bytes(b"old")
        with pytest.raises(openscript_store.ScriptConflict) as refused:
            openscript_store.write_script(folder, "a.oscript", b"new", replace=False)
        assert refused.value.compiled is False
        assert sorted(entry.name for entry in folder.iterdir()) == ["a.oscript"]
        assert (folder / "a.oscript").read_bytes() == b"old"
