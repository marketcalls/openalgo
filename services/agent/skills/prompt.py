"""The prompt section that tells the model which skills it can read.

Progressive disclosure, in agno's sense: the prompt carries only each skill's
name, its one-paragraph description and the notes on how to apply it here. The
instructions and the reference pages are fetched with the skill tools when a job
calls for them, so a 34k-character reference costs nothing on a turn that does
not need it.

Agno's own skills snippet is never shown, because the builder passes the whole
system prompt as a verbatim system message. This section is its replacement.
"""

from __future__ import annotations

from pathlib import Path

from services.agent.prompts import PromptSection
from services.agent.skills.loader import available_skills

#: Sort weight: after the code-writing rules (50), before the drawing rules (55).
SKILLS_SECTION_ORDER = 52

_PREAMBLE = """
Some authoring jobs have a skill: written guidance you read on demand. Before
writing anything a skill below covers, call get_skill_instructions for it, then
get_skill_reference for each page those instructions tell you to read. Never
write it from memory. Instructions already read in this conversation need not be
fetched again.

The skills were written for a reader that can run commands and write files. You
cannot, so where a skill says to run something, do what its "Here" note says
instead.
""".strip()


def skills_section(surface: str, root: Path | None = None) -> PromptSection | None:
    """Build the skills section for one surface, from the folders as they are now.

    Args:
        surface: ``chat``, ``chart`` or ``voice``.
        root: Repository root. Defaults to the loader's; tests pass their own.

    Returns:
        A :class:`PromptSection` keyed ``skills``, or None when no skill is
        offered on the surface or none loads, so a surface without skills is
        never taught tools it does not have.
    """
    skills = available_skills(surface, root)
    if not skills:
        return None

    entries = [
        f"- {skill.name}: {skill.description}\n  Here: {' '.join(skill.spec.agent_notes.split())}"
        for skill in skills
    ]
    return PromptSection(
        key="skills",
        title="SKILLS",
        order=SKILLS_SECTION_ORDER,
        body=_PREAMBLE + "\n\n" + "\n".join(entries),
    )
