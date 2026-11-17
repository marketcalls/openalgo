"""The skills the agent may read, and where each one is offered.

A skill is a folder of written guidance (a ``SKILL.md`` plus reference pages)
that teaches how to author one kind of thing for this platform. The folders live
in the repository under ``.claude/skills/`` and are shared with Claude Code,
which is why they talk about running validators and writing files: that is how
Claude Code applies them. The agent cannot run anything, so each entry here
carries ``agent_notes``, a few sentences that map those steps onto the agent's
own tools.

Adding a skill
--------------

One :class:`SkillSpec` in :data:`SKILLS` and nothing else. The loader reads the
folder live on every call, so editing a ``SKILL.md`` or a reference page takes
effect on the next message without a restart, and the prompt summary, the tool
results and the list of references all follow from the folder.

The one thing an entry cannot widen on its own is the surfaces the skills
toolkit is built for (``services/agent/tools/__init__.py``). A test pins that
every surface named here is one the toolkit is offered on, so a skill offered on
a new surface fails loudly instead of being listed in a prompt whose tools
cannot read it.

Voice is deliberately absent from both entries. Authoring a script or a workflow
is a typing job, for the reason ``CHAT_ONLY`` gives in the tool registry.
"""

from __future__ import annotations

from dataclasses import dataclass

from services.agent.tools import SURFACE_CHART, SURFACE_CHAT

#: Folders, relative to the skill folder, that hold reference pages. Both
#: spellings exist in this repository: the CI generators write ``reference/``
#: and older skills use ``references/``.
DEFAULT_REFERENCE_DIRS: tuple[str, ...] = ("reference", "references")

#: File types a reference may be. Text only: nothing in a skill folder is ever
#: executed, and a script is not a reference.
DEFAULT_REFERENCE_SUFFIXES: tuple[str, ...] = (".md", ".txt", ".json")


@dataclass(frozen=True)
class SkillSpec:
    """One skill the agent may read.

    Attributes:
        name: The name the model passes to the skill tools. Matches the
            ``name`` in the skill's frontmatter; the spec wins if they differ.
        folder: The skill folder, relative to the repository root.
        surfaces: Surfaces the skill is offered on.
        agent_notes: How the skill's own steps map onto the agent's tools.
            Shown in the prompt and with the instructions, because the
            ``SKILL.md`` itself was written for a reader that can run commands.
        reference_dirs: Folders inside the skill folder whose files the model
            may read with ``get_skill_reference``.
        reference_suffixes: File types those folders may serve.
    """

    name: str
    folder: str
    surfaces: frozenset[str]
    agent_notes: str
    reference_dirs: tuple[str, ...] = DEFAULT_REFERENCE_DIRS
    reference_suffixes: tuple[str, ...] = DEFAULT_REFERENCE_SUFFIXES

    def offered_on(self, surface: str) -> bool:
        """Report whether this skill is offered on a surface.

        Args:
            surface: ``chat``, ``chart`` or ``voice``.

        Returns:
            True when the surface is one of :attr:`surfaces`.
        """
        return (surface or "").strip().lower() in self.surfaces


#: Every skill the agent may read. Order is the order the prompt lists them in.
SKILLS: tuple[SkillSpec, ...] = (
    SkillSpec(
        name="openscript",
        folder=".claude/skills/openscript",
        # Chat and the chart panel: a study is written beside the chart it
        # plots on as often as on the conversation page.
        surfaces=frozenset({SURFACE_CHAT, SURFACE_CHART}),
        agent_notes=(
            "You cannot run validate.mjs, the importer or any node command, and nothing "
            "compiles here. Check every name against reference/library.md (a planned name "
            "fails with OS2020) and reference/pitfalls.md, show the operator the full "
            "source, then save it with save_openscript. It is stored as source only: the "
            "trader opens it in the OpenScript editor on /trading, where it compiles, and "
            "saving it there stores the compiled program a strategy needs to run."
        ),
        # The worked examples are the files that are known to compile, and the
        # skill tells its reader to study them, so they are served as text.
        reference_dirs=("reference", "examples"),
        reference_suffixes=(".md", ".txt", ".json", ".oscript"),
    ),
    SkillSpec(
        name="flow-builder",
        folder=".claude/skills/flow-builder",
        # Chat only, matching the Flow toolkit it hands off to.
        surfaces=frozenset({SURFACE_CHAT}),
        agent_notes=(
            "You cannot run validate.py, curl or SQL. Validate with validate_flow instead "
            "of validate.py, and save with save_flow instead of the import route; it "
            "imports the workflow inactive and the operator activates it in /flow. "
            "validate_flow does not flag a data key nothing reads, so copy every key from "
            "reference/nodes.md exactly."
        ),
    ),
)


def skills_for_surface(surface: str) -> tuple[SkillSpec, ...]:
    """Return the skills offered on one surface, in registry order.

    Args:
        surface: ``chat``, ``chart`` or ``voice``.

    Returns:
        The matching specs. Empty for a surface with none.
    """
    return tuple(spec for spec in SKILLS if spec.offered_on(surface))


def find_skill(name: str, surface: str) -> SkillSpec | None:
    """Find a skill by name among those offered on a surface.

    Args:
        name: The skill name, compared case-insensitively.
        surface: The run's surface. A skill not offered there is not found.

    Returns:
        The spec, or None.
    """
    wanted = (name or "").strip().lower()
    for spec in skills_for_surface(surface):
        if spec.name.lower() == wanted:
            return spec
    return None
