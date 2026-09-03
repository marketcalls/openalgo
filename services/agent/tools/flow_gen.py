"""Validate generated Flow workflow JSON, and import it as an inactive workflow.

The schema lives in one place
-----------------------------

``docs/prompt/flow-import-format.md`` is the source of truth for the workflow
shape: the top-level object, every node type, every edge variant, the variable
interpolation grammar and the source-handle vocabulary. It is written to be fed
to a model as a system prompt, so the agent is given that file rather than a
paraphrase of it, and this module holds no copy of the schema. A second copy
would drift, and a drifted copy of a schema is worse than none: it teaches the
model a node type the importer will reject.

The validator is the ground truth
---------------------------------

``services.flow_workflow_validator.validate_workflow`` is called directly, at
the same level the ``/flow`` import endpoint uses (``require_name=True``,
``strict=True``), so anything this toolkit accepts is exactly what that endpoint
would accept. Its ``errors[]`` entries, each ``{path, code, message}``, go back
to the model verbatim inside a ``RetryAgentRun`` so it corrects its own JSON
instead of shipping a graph that fails later at activation or mid-execution.

**An invalid workflow is never saved.** Validation runs before the row is
created, not after.

An imported workflow arrives inactive
-------------------------------------

``FlowWorkflow.is_active`` defaults to false and nothing here changes it. The
user activates the workflow in ``/flow`` themselves, which is where its webhook
and its API key are wired up. This toolkit cannot activate a workflow and cannot
execute one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from services.agent.prompts import wrap_tool_result
from services.agent.tools.base import OpenAlgoToolkit, strip_code_fence
from services.flow_workflow_validator import (
    migrate_legacy_node_data,
    trigger_config,
    validate_workflow,
)
from utils.logging import get_logger

try:
    from agno.exceptions import RetryAgentRun
except ImportError as exc:  # pragma: no cover - exercised only without the dependency
    raise ImportError(
        "services.agent.tools.flow_gen requires the 'agno' package. Install it with: uv add agno"
    ) from exc

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.agent.tools import ToolContext

logger = get_logger(__name__)

#: Where the model is sent for the schema. Never paraphrased here.
SCHEMA_DOC = "docs/prompt/flow-import-format.md"

#: Upper bound on one workflow document. The validator caps nodes and edges
#: itself; this stops a runaway string before it is parsed.
MAX_JSON_CHARS = 400_000

#: ``flow_workflows.name`` is String(255) and the import suffix costs 11 more.
MAX_NAME_CHARS = 200

#: The suffix ``/flow``'s own import endpoint appends, kept identical so an
#: agent-imported workflow reads the same as a hand-imported one in the list.
IMPORT_SUFFIX = " (imported)"

#: Most validator errors handed back in one message. A graph with hundreds of
#: errors has one root cause, and the first few carry it.
MAX_REPORTED_ERRORS = 50


class FlowGenToolkit(OpenAlgoToolkit):
    """Validate Flow workflow JSON, and import a valid one as an inactive workflow."""

    def __init__(self, context: ToolContext) -> None:
        """Register the two tools with agno.

        Args:
            context: The run's tool context.
        """
        super().__init__(
            context,
            name="flow_gen",
            tools=[self.validate_flow, self.save_flow],
            requires_confirmation_tools=["save_flow"],
        )

    # -- tools ---------------------------------------------------------------

    def validate_flow(self, workflow_json: str) -> str:
        """Check Flow workflow JSON against the real Flow validator, saving nothing.

        Use this while you are still writing the graph. It runs exactly the
        checks the /flow import endpoint runs, so a workflow that passes here
        will import, and nothing is written to the database either way. The
        workflow name is not required at this stage because save_flow takes it
        as its own argument.

        When the workflow is invalid this tool does not return: it comes back as
        an error carrying the validator's own errors[], each entry a
        {path, code, message}. Correct exactly those paths and call again. Do
        not invent a node type to satisfy an error; if a requirement has no
        matching node type, say so to the user in prose.

        Args:
            workflow_json: The complete workflow as a JSON object string, of the
                form ``{"name": ..., "nodes": [...], "edges": [...]}``. Node
                types, node data fields, edge shapes and the handle vocabulary
                are defined in docs/prompt/flow-import-format.md; copy type
                names from it verbatim.

        Returns:
            JSON with ``valid``, ``saved`` (always false), ``node_count``,
            ``edge_count``, the trigger configuration found, and any legacy
            fields that were upgraded during the check.
        """
        payload, migrations = self._prepare(workflow_json)
        self._reject_if_invalid("validate_flow", payload, require_name=False)

        nodes = payload.get("nodes") or []
        edges = payload.get("edges") or []
        return self._result(
            "validate_flow",
            {
                "ok": True,
                "valid": True,
                "saved": False,
                "name": payload.get("name"),
                "node_count": len(nodes) if isinstance(nodes, list) else 0,
                "edge_count": len(edges) if isinstance(edges, list) else 0,
                "trigger": trigger_config(nodes if isinstance(nodes, list) else []),
                "migrations": migrations,
                "next_step": (
                    "Nothing was saved. Show the workflow to the user, then call save_flow "
                    "with a name to import it."
                ),
            },
        )

    def save_flow(self, name: str, workflow_json: str) -> str:
        """Validate Flow workflow JSON and import it as a new INACTIVE workflow.

        The workflow is validated first, with the same validator and the same
        strictness the /flow import endpoint uses. An invalid workflow is never
        saved: the call comes back as an error carrying the validator's own
        errors[], and you correct those paths and call again.

        A workflow imported this way is created INACTIVE and does not run. The
        user opens /flow, reviews it and activates it there, which is also where
        its webhook and API key are set up. Say that in your answer: this tool
        cannot activate a workflow and cannot execute one.

        Args:
            name: Name for the workflow, for example
                ``NIFTY opening range breakout``. Up to 200 characters. It is
                stored with " (imported)" appended, the same way the /flow
                import screen stores one, and it overrides any name inside the
                JSON.
            workflow_json: The complete workflow as a JSON object string, of the
                form ``{"name": ..., "nodes": [...], "edges": [...]}``. Node
                types, node data fields, edge shapes and the handle vocabulary
                are defined in docs/prompt/flow-import-format.md; copy type
                names from it verbatim and never invent one.

        Returns:
            JSON with ``saved``, ``workflow_id``, the stored ``name``,
            ``is_active`` (always false), ``node_count``, ``edge_count`` and the
            next step the user takes in /flow.
        """
        clean_name = self._require_name(name)
        payload, migrations = self._prepare(workflow_json)
        payload["name"] = clean_name
        self._reject_if_invalid("save_flow", payload, require_name=True)

        nodes = payload.get("nodes") or []
        edges = payload.get("edges") or []
        description = payload.get("description")
        if not isinstance(description, str):
            description = None

        stored_name = f"{clean_name}{IMPORT_SUFFIX}"
        audit_args = {
            "name": stored_name,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

        with self.audited("save_flow", audit_args) as audit:
            workflow_id = self._create_workflow(stored_name, description, nodes, edges)

            if workflow_id is None:
                audit.record(ok=False, response={"status": "error", "message": "create failed"})
                return self._result(
                    "save_flow",
                    {
                        "ok": False,
                        "saved": False,
                        "error": (
                            "The workflow passed validation but could not be written to the "
                            "database. This is a platform failure, not a problem with the "
                            "JSON. Report it to the user rather than calling the tool again."
                        ),
                    },
                )

            payload_out = {
                "ok": True,
                "saved": True,
                "workflow_id": workflow_id,
                "name": stored_name,
                "is_active": False,
                "node_count": len(nodes),
                "edge_count": len(edges),
                "migrations": migrations,
                "next_step": (
                    "The workflow was imported and is INACTIVE, so it is not running. The "
                    "user opens /flow to review and activate it. This tool cannot activate "
                    "or execute a workflow."
                ),
            }
            audit.record(ok=True, response={"workflow_id": workflow_id, "name": stored_name})

        logger.info("Agent imported Flow workflow %s as id %s", stored_name, workflow_id)
        return self._result("save_flow", payload_out)

    # -- input handling ------------------------------------------------------

    def _require_name(self, name: str) -> str:
        """Check the workflow name is usable and within the column's width.

        Args:
            name: The ``name`` argument as received.

        Returns:
            The trimmed name.

        Raises:
            RetryAgentRun: When it is empty or too long.
        """
        if not isinstance(name, str) or not name.strip():
            self.invalid_argument(
                "name",
                "it is empty.",
                "Pass a short descriptive name such as 'NIFTY opening range breakout'.",
            )
        cleaned = name.strip()
        if len(cleaned) > MAX_NAME_CHARS:
            self.invalid_argument(
                "name",
                f"it is {len(cleaned)} characters, over the {MAX_NAME_CHARS} limit.",
                "Shorten it to a title rather than a description.",
            )
        return cleaned

    def _prepare(self, workflow_json: Any) -> tuple[dict[str, Any], list[str]]:
        """Parse the workflow argument and upgrade any legacy node payloads.

        The legacy migration is the one the ``/flow`` import endpoint applies,
        run before validation for the same reason: an older exported workflow
        should import as its canonical shape rather than being stored carrying a
        field no reader honours.

        Args:
            workflow_json: The JSON document, as a string. A mapping is accepted
                too, since some model runtimes deliver an object argument
                already parsed.

        Returns:
            The parsed workflow object and the human-readable migration notes.

        Raises:
            RetryAgentRun: When the argument is not a JSON object.
        """
        payload = self._parse(workflow_json)

        migrations: list[str] = []
        nodes = payload.get("nodes")
        if isinstance(nodes, list):
            payload["nodes"], migrations = migrate_legacy_node_data(nodes)
        return payload, migrations

    def _parse(self, workflow_json: Any) -> dict[str, Any]:
        """Turn the ``workflow_json`` argument into a mutable dictionary.

        Args:
            workflow_json: The argument as received.

        Returns:
            A shallow copy of the workflow object, safe to modify.

        Raises:
            RetryAgentRun: When it is not a string, is too large, does not parse
                as JSON, or does not parse to an object.
        """
        if isinstance(workflow_json, Mapping):
            return dict(workflow_json)

        if not isinstance(workflow_json, str):
            self.invalid_argument(
                "workflow_json",
                f"it is a {type(workflow_json).__name__}, not a JSON string.",
                f"Send the workflow object as JSON text, as described in {SCHEMA_DOC}.",
            )

        if len(workflow_json) > MAX_JSON_CHARS:
            self.invalid_argument(
                "workflow_json",
                f"it is {len(workflow_json)} characters, over the {MAX_JSON_CHARS} limit.",
                "Build a smaller workflow.",
            )

        text = strip_code_fence(workflow_json)
        if not text:
            self.invalid_argument(
                "workflow_json",
                "it is empty.",
                f"Send the whole workflow object as JSON text, as described in {SCHEMA_DOC}.",
            )

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RetryAgentRun(
                f"The 'workflow_json' argument is not valid JSON: {exc.msg} at line "
                f"{exc.lineno}, column {exc.colno}. Nothing was validated and nothing was "
                "saved. Emit the JSON object alone, with no code fence, no comments and no "
                f"trailing commas, as {SCHEMA_DOC} requires, and call the tool again."
            ) from exc

        if not isinstance(parsed, dict):
            self.invalid_argument(
                "workflow_json",
                f"it parses to a JSON {type(parsed).__name__}, not an object.",
                'The workflow must be {"name": ..., "nodes": [...], "edges": [...]}. '
                f"See {SCHEMA_DOC}.",
            )

        return dict(parsed)

    # -- validation ----------------------------------------------------------

    def _reject_if_invalid(self, tool: str, payload: dict[str, Any], *, require_name: bool) -> None:
        """Run the real Flow validator and refuse the workflow if it reports anything.

        ``strict=True`` is not optional here: it is the level the import
        endpoint enforces, and it is what checks required node fields, the
        single-trigger rule, reachability and cycles. Validating loosely and
        saving anyway would move the failure to activation or to the middle of a
        live run.

        Args:
            tool: Name of the calling tool, used to label the error block.
            payload: The prepared workflow object.
            require_name: Whether a top-level name is required. False while
                validating a draft, since ``save_flow`` supplies the name.

        Raises:
            RetryAgentRun: When the validator returns any error, carrying those
                entries verbatim.
        """
        errors = validate_workflow(payload, require_name=require_name, strict=True)
        if not errors:
            return

        reported = errors[:MAX_REPORTED_ERRORS]
        block = wrap_tool_result(
            tool,
            self.to_json(
                {"valid": False, "saved": False, "error_count": len(errors), "errors": reported}
            ),
        )
        omitted = (
            f" {len(errors) - len(reported)} further error(s) are not listed."
            if len(errors) > len(reported)
            else ""
        )
        raise RetryAgentRun(
            f"The workflow failed Flow's own validator with {len(errors)} error(s), so nothing "
            f"was saved. Each entry names the JSON path, a code and a reason.{omitted}\n"
            f"{block}\n"
            f"Fix exactly those paths and call the tool again. Node types and node data "
            f"fields are defined in {SCHEMA_DOC}; copy them verbatim and never invent a node "
            "type. If a requirement has no matching node type, tell the user in prose instead."
        )

    # -- persistence ---------------------------------------------------------

    @staticmethod
    def _create_workflow(
        name: str, description: str | None, nodes: list[Any], edges: list[Any]
    ) -> int | None:
        """Create the workflow row and return its id.

        ``database.flow_db.create_workflow`` returns None on failure rather than
        raising, so the result is checked here instead of being unwrapped as a
        service tuple, which would read a None as success.

        The scoped session is removed afterwards. A toolkit runs on the agent's
        real OS thread, which has no Flask app context, so the per-request
        teardown never fires and the session would otherwise stay bound to that
        thread holding its connection for the life of the worker.

        Args:
            name: Stored workflow name, suffix already applied.
            description: Optional description from the JSON.
            nodes: The workflow's nodes.
            edges: The workflow's edges.

        Returns:
            The new workflow id, or None when the row could not be created.
        """
        from database.flow_db import create_workflow, db_session

        try:
            workflow = create_workflow(name=name, description=description, nodes=nodes, edges=edges)
            if workflow is None:
                return None
            return int(workflow.id)
        except Exception:
            logger.exception("Could not create the agent-generated Flow workflow %r", name)
            return None
        finally:
            db_session.remove()

    # -- helpers -------------------------------------------------------------

    def _result(self, tool: str, payload: Any) -> str:
        """Serialise a payload and label it as data for the model.

        Args:
            tool: The tool name, written into the block's opening tag.
            payload: The result to return.

        Returns:
            A ``<tool_result>`` block wrapping the capped JSON.
        """
        return wrap_tool_result(tool, self.to_json(payload))
