"""Read a skill's instructions and reference pages, a page at a time.

The prompt lists each skill offered on the run's surface (see
``services/agent/skills/prompt.py``); these two tools are how the model reads
one. Both are read-only, both read the folder live so an edit applies on the
next call, and neither can name a skill the run's surface is not offered or a
file outside the skill's reference folders. Nothing here executes anything.

Long text is paged, never truncated
-----------------------------------

A reference page can run to 34k characters and a skill result is capped at
:data:`SKILL_RESULT_CHARS`. Cutting it to fit would hand the model the first third of a
name table and let it believe it had read the whole of it. So each call returns
a slice that fits the budget with ``total_chars`` and ``next_offset`` beside it,
and the model continues from ``next_offset`` until it is null. The slices are
contiguous and non-overlapping, so the pages concatenate back to the file
exactly.

Threading: the reads are local file I/O on the agent's thread and the only lock
involved is the loader cache's, which is real. No service code is called, so
nothing here goes through the hub.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from services.agent.prompts import wrap_tool_result
from services.agent.skills import registry
from services.agent.skills.loader import LoadedSkill, SkillError, load_skill, read_reference
from services.agent.tools.base import OpenAlgoToolkit, dumps_capped
from utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.agent.tools import ToolContext

logger = get_logger(__name__)

#: Most characters one skill result may carry. Larger than the base class's
#: ``MAX_JSON_CHARS`` on purpose: that cap protects the context from market data
#: a tool cannot bound, while a skill page is the owner's own document that the
#: model reads in full either way. At the shared cap, writing one OpenScript
#: study took eighteen calls of paging, close to the run's tool-call limit; the
#: text read is the same at any page size, only the number of calls changes.
SKILL_RESULT_CHARS = 32_000

#: Characters of text tried for one page before the result is measured. JSON
#: escaping grows text by a few percent, so this leaves room under the cap for
#: the envelope; :meth:`SkillsToolkit._paged` shrinks it when a page with many
#: quotes or backslashes still does not fit.
PAGE_CHARS = 30_000

#: Characters kept free under :data:`SKILL_RESULT_CHARS` for the envelope.
_PAGE_HEADROOM = 200


class SkillsToolkit(OpenAlgoToolkit):
    """Read the skills offered on this surface: instructions first, then references."""

    def __init__(self, context: ToolContext) -> None:
        """Register the two read-only tools with agno.

        Args:
            context: The run's tool context.
        """
        super().__init__(
            context,
            name="skills",
            tools=[self.get_skill_instructions, self.get_skill_reference],
        )

    # -- tools ---------------------------------------------------------------

    def get_skill_instructions(self, skill_name: str, offset: int = 0) -> str:
        """Read a skill's instructions: how to author one kind of thing on this platform.

        Call this before writing anything a skill in the SKILLS section covers,
        then read the reference pages it names with get_skill_reference. Long
        instructions come back in pages: while next_offset is not null, call
        again with offset set to it to read the rest. The skill was written for
        a reader that can run commands; agent_notes says how to do each step
        with your own tools instead.

        Args:
            skill_name: A skill name exactly as the SKILLS section lists it, for
                example ``openscript`` or ``flow-builder``.
            offset: Character offset to read from. 0 for the first page, then
                the next_offset the previous page returned.

        Returns:
            JSON with ``skill``, ``content`` (this page of the instructions),
            ``offset``, ``next_offset`` (null on the last page) and
            ``total_chars``. The first page also carries ``agent_notes`` and
            ``references``, the paths get_skill_reference accepts.
        """
        tool = "get_skill_instructions"
        skill = self._find(tool, skill_name)
        if isinstance(skill, str):
            return skill

        extra: dict[str, Any] = {}
        if not offset:
            extra = {"agent_notes": skill.spec.agent_notes, "references": list(skill.references)}
        return self._paged(tool, skill, skill.instructions, offset, extra)

    def get_skill_reference(self, skill_name: str, reference_path: str, offset: int = 0) -> str:
        """Read one reference page of a skill, such as a name table or a list of pitfalls.

        Use the paths get_skill_instructions listed under references, or a path
        the instructions name. Long pages come back in pages: while next_offset
        is not null, call again with offset set to it. Read a page to the end
        before relying on it; a table you have half read looks complete.

        Args:
            skill_name: A skill name exactly as the SKILLS section lists it, for
                example ``openscript``.
            reference_path: The page's path inside the skill folder, for
                example ``reference/library.md``. A bare file name such as
                ``library.md`` works when only one page has that name.
            offset: Character offset to read from. 0 for the first page, then
                the next_offset the previous page returned.

        Returns:
            JSON with ``skill``, ``reference``, ``content`` (this page),
            ``offset``, ``next_offset`` (null on the last page) and
            ``total_chars``.
        """
        tool = "get_skill_reference"
        skill = self._find(tool, skill_name)
        if isinstance(skill, str):
            return skill

        try:
            text = read_reference(skill, reference_path)
        except SkillError as exc:
            return self._result(
                tool,
                {
                    "ok": False,
                    "skill": skill.name,
                    "error": str(exc),
                    "references": list(skill.references),
                },
            )
        return self._paged(tool, skill, text, offset, {"reference": reference_path})

    # -- helpers -------------------------------------------------------------

    def _find(self, tool: str, skill_name: str) -> LoadedSkill | str:
        """Load a skill offered on this run's surface, or explain why not.

        Args:
            tool: The calling tool, for the result label.
            skill_name: The name the model passed.

        Returns:
            The loaded skill, or a finished tool result naming the skills that
            are available when the name is unknown or the skill cannot be read.
        """
        spec = registry.find_skill(skill_name, self.surface)
        offered = [entry.name for entry in registry.skills_for_surface(self.surface)]
        if spec is None:
            return self._result(
                tool,
                {
                    "ok": False,
                    "error": (
                        f"There is no skill called {skill_name!r} here. Call again with one of "
                        "the available_skills names, or write without a skill if none fits."
                    ),
                    "available_skills": offered,
                },
            )

        skill = load_skill(spec)
        if skill is None:
            return self._result(
                tool,
                {
                    "ok": False,
                    "error": (
                        f"The {spec.name} skill could not be read on this server just now. "
                        "Tell the operator its guidance is unavailable, and carry on carefully "
                        "without it rather than calling again."
                    ),
                    "available_skills": offered,
                },
            )
        return skill

    def _paged(
        self, tool: str, skill: LoadedSkill, text: str, offset: Any, extra: dict[str, Any]
    ) -> str:
        """Return the page of ``text`` that starts at ``offset`` and fits the budget.

        The page ends on a line break when one falls in its second half, so a
        reader is not handed half a table row, and is shrunk until the whole
        result fits under :data:`SKILL_RESULT_CHARS` without truncation ever
        applying.

        Args:
            tool: The calling tool.
            skill: The skill the text belongs to.
            text: The whole text being paged.
            offset: Where this page starts, as the model sent it.
            extra: Fields added to the result beside the page.

        Returns:
            A ``<tool_result>`` block.

        Raises:
            RetryAgentRun: When ``offset`` is not a whole number between 0 and
                the text's length.
        """
        total = len(text)
        if isinstance(offset, bool) or not isinstance(offset, int):
            try:
                offset = int(str(offset).strip())
            except ValueError:
                offset = -1
        if offset < 0 or offset > total:
            self.invalid_argument(
                "offset",
                f"it is outside the text, which is {total} characters long.",
                "Pass 0 for the first page, or the next_offset the previous page returned.",
            )

        size = max(1, min(PAGE_CHARS, total - offset))
        budget = SKILL_RESULT_CHARS - _PAGE_HEADROOM
        while True:
            end = min(total, offset + size)
            if end < total:
                newline = text.rfind("\n", offset + size // 2, end)
                if newline != -1:
                    end = newline + 1
            payload = {
                "ok": True,
                "skill": skill.name,
                **extra,
                "offset": offset,
                "next_offset": end if end < total else None,
                "total_chars": total,
                "content": text[offset:end],
            }
            if end < total:
                payload["note"] = (
                    f"This is characters {offset} to {end} of {total}. Call {tool} again with "
                    f"offset={end} to read the next page."
                )
            measured = len(dumps_capped(payload, limit=sys.maxsize))
            if measured <= budget or size <= 1:
                return self._result(tool, payload)
            # Shrink in proportion to the overshoot, and always by at least one
            # character, so the loop ends.
            size = max(1, min(size - 1, int(size * budget / measured * 0.95)))

    def _result(self, tool: str, payload: Any) -> str:
        """Serialise a payload and label it as data for the model.

        Skill text is written by the repository's owner, but it is still text
        the model did not write, so it crosses the same boundary as any tool
        result.

        Args:
            tool: The tool name, written into the block's opening tag.
            payload: The result to return.

        Returns:
            A ``<tool_result>`` block wrapping the capped JSON.
        """
        return wrap_tool_result(tool, dumps_capped(payload, SKILL_RESULT_CHARS))
