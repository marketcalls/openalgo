"""Read a skill folder from disk, live, safely.

Every call reads the folder as it is now. The owner edits these files often and
the next message should see the edit without a restart, so nothing is loaded at
import and nothing is kept past a change: parsed files are cached under a key
that includes their modification time and size, and an edited file is simply a
different key. The cache is a :class:`utils.thread_safe_cache.LockedTTLCache`,
whose lock is real, because the same files are read from a request (the prompt
summary, on the hub under eventlet) and from the agent's real OS thread (the
tools). Its critical sections are dictionary work only; the file reads happen
outside it.

What the model can name, and what it can reach
-----------------------------------------------

The model chooses a skill name and a reference path, so both are treated as
hostile input. A skill is found only through the registry, never by joining a
model-chosen name onto a path. A reference path must name a file inside one of
the skill's declared reference folders, with an allowed suffix, and it is
resolved (following any symlink) and checked to still sit inside the skill
folder, so neither ``../`` nor a link pointing elsewhere reaches another file.
Every read is capped at :data:`MAX_FILE_BYTES`.

Nothing in a skill folder is executed. Agno's own skills toolkit offers a tool
that runs a skill's scripts with arguments the model chooses; this module has no
such path and never will.

A skill that is missing or malformed is skipped with a warning, once per version
of the file. It costs that skill and never the agent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from services.agent.skills import registry
from services.agent.skills.registry import SkillSpec
from utils.logging import get_logger
from utils.thread_safe_cache import LockedTTLCache

logger = get_logger(__name__)

#: The repository root that each :attr:`SkillSpec.folder` is relative to.
REPO_ROOT = Path(__file__).resolve().parents[3]

#: The file holding a skill's frontmatter and instructions.
SKILL_FILE = "SKILL.md"

#: Largest file this module reads. The biggest page shipped today is about 34k
#: characters; this leaves room to grow while refusing anything that is not a
#: page of guidance.
MAX_FILE_BYTES = 256 * 1024

#: Most reference files listed for one skill.
MAX_REFERENCES = 100

#: Longest description carried into the prompt. Descriptions are written for
#: deciding when a skill applies, and one that has grown into a manual would
#: crowd out the rest of the prompt.
MAX_DESCRIPTION_CHARS = 600

# Parsed files keyed by (kind, path, mtime_ns, size). The TTL only bounds how
# long a superseded version lingers; correctness comes from the key.
_CACHE = LockedTTLCache(maxsize=256, ttl=600)

# Problems already logged, keyed the same way, so a broken skill warns once per
# version of the file rather than on every message.
_WARNED = LockedTTLCache(maxsize=256, ttl=600)

_FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)(.*)\Z", re.DOTALL)


class SkillError(Exception):
    """A skill file could not be served. ``str()`` is a sentence for the model."""


@dataclass(frozen=True)
class LoadedSkill:
    """One skill as it is on disk right now.

    Attributes:
        spec: The registry entry.
        description: The frontmatter description, whitespace collapsed.
        instructions: The body of ``SKILL.md`` after the frontmatter.
        references: Reference paths relative to the skill folder, in POSIX form,
            exactly as ``get_skill_reference`` accepts them.
    """

    spec: SkillSpec
    description: str
    instructions: str
    references: tuple[str, ...]

    @property
    def name(self) -> str:
        """The skill's name, as the registry spells it."""
        return self.spec.name


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def _warn_once(key: tuple, message: str, *args: object) -> None:
    """Log a warning the first time a given problem is seen.

    Args:
        key: Identifies the problem and the file version it was found in.
        message: Log format string.
        *args: Its arguments.
    """
    if _WARNED.get(key) is None:
        _WARNED[key] = True
        logger.warning(message, *args)


def _read_text(path: Path) -> str:
    """Read a text file through the cache, capped and normalised.

    Args:
        path: An already-vetted absolute path.

    Returns:
        The text, decoded as UTF-8 with any byte order mark removed and line
        endings normalised to ``\\n``, so offsets are the same on every platform.

    Raises:
        SkillError: The file is missing, unreadable or over the size cap.
    """
    try:
        stat = path.stat()
    except OSError as exc:
        raise SkillError(f"{path.name} could not be read.") from exc

    if stat.st_size > MAX_FILE_BYTES:
        raise SkillError(
            f"{path.name} is {stat.st_size} bytes, over the {MAX_FILE_BYTES} byte limit for a "
            "skill page, so it is not served."
        )

    key = ("text", str(path), stat.st_mtime_ns, stat.st_size)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise SkillError(f"{path.name} could not be read.") from exc
    if len(raw) > MAX_FILE_BYTES:
        # Grew between the stat and the read.
        raise SkillError(f"{path.name} is over the size limit for a skill page.")

    text = raw.decode("utf-8", errors="replace")
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    _CACHE[key] = text
    return text


def parse_skill_md(text: str) -> tuple[dict, str]:
    """Split a ``SKILL.md`` into its YAML frontmatter and its body.

    Args:
        text: The file's text, line endings already normalised.

    Returns:
        The frontmatter mapping and the instructions body, stripped.

    Raises:
        ValueError: There is no frontmatter block, it is not valid YAML, it is
            not a mapping, or it carries no description.
    """
    match = _FRONTMATTER.match(text)
    if not match:
        raise ValueError("it has no frontmatter block between --- lines")
    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise ValueError(f"its frontmatter is not valid YAML ({exc})") from exc
    if not isinstance(frontmatter, dict):
        raise ValueError("its frontmatter is not a mapping of keys to values")
    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("its frontmatter has no description")
    return frontmatter, match.group(2).strip()


def _short_description(text: str) -> str:
    """Collapse whitespace and cap a description at a sentence boundary.

    Args:
        text: The frontmatter description.

    Returns:
        One line of at most :data:`MAX_DESCRIPTION_CHARS` characters.
    """
    flat = " ".join(text.split())
    if len(flat) <= MAX_DESCRIPTION_CHARS:
        return flat
    cut = flat.rfind(". ", 0, MAX_DESCRIPTION_CHARS)
    if cut > MAX_DESCRIPTION_CHARS // 2:
        return flat[: cut + 1]
    return flat[: MAX_DESCRIPTION_CHARS - 3].rstrip() + "..."


def skill_dir(spec: SkillSpec, root: Path | None = None) -> Path | None:
    """Resolve a skill's folder and check it stays inside the repository.

    Args:
        spec: The registry entry.
        root: Repository root. Defaults to :data:`REPO_ROOT`; tests pass their
            own.

    Returns:
        The resolved folder, or None when it is missing or resolves outside the
        root (a symlinked folder pointing elsewhere, for instance).
    """
    base = (root or REPO_ROOT).resolve()
    try:
        folder = (base / spec.folder).resolve()
    except OSError:
        return None
    if not folder.is_relative_to(base) or not folder.is_dir():
        return None
    return folder


def _is_hidden(relative: PurePosixPath) -> bool:
    """Whether any part of a relative path is a dotfile or dot folder."""
    return any(part.startswith(".") for part in relative.parts)


def list_references(spec: SkillSpec, folder: Path) -> tuple[str, ...]:
    """List the reference files a skill may serve.

    Args:
        spec: The registry entry, which names the reference folders and the
            allowed suffixes.
        folder: The skill's resolved folder.

    Returns:
        Paths relative to the skill folder, in POSIX form and sorted, capped at
        :data:`MAX_REFERENCES`. A file whose real location is outside the skill
        folder is left out.
    """
    suffixes = {suffix.lower() for suffix in spec.reference_suffixes}
    found: list[str] = []
    for name in spec.reference_dirs:
        directory = folder / name
        if not directory.is_dir():
            continue
        try:
            candidates = sorted(directory.rglob("*"))
        except OSError:
            logger.exception("Could not list the reference folder %s", directory)
            continue
        for path in candidates:
            if path.suffix.lower() not in suffixes:
                continue
            relative = PurePosixPath(path.relative_to(folder).as_posix())
            if _is_hidden(relative):
                continue
            try:
                if not path.is_file() or not path.resolve().is_relative_to(folder):
                    continue
            except OSError:
                continue
            found.append(str(relative))
            if len(found) >= MAX_REFERENCES:
                return tuple(found)
    return tuple(found)


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


def load_skill(spec: SkillSpec, root: Path | None = None) -> LoadedSkill | None:
    """Read one skill as it is on disk now.

    Args:
        spec: The registry entry.
        root: Repository root. Defaults to :data:`REPO_ROOT`.

    Returns:
        The skill, or None when its folder or ``SKILL.md`` is missing or
        malformed. Each such problem is logged once per version of the file.
    """
    folder = skill_dir(spec, root)
    if folder is None:
        _warn_once(
            ("missing", spec.name, str(root or REPO_ROOT)),
            "Agent skill %r is registered but its folder %s is missing; it is not offered",
            spec.name,
            spec.folder,
        )
        return None

    skill_file = folder / SKILL_FILE
    try:
        stat = skill_file.stat()
        text = _read_text(skill_file)
        key = ("skill", str(skill_file), stat.st_mtime_ns, stat.st_size)
        parsed = _CACHE.get(key)
        if parsed is None:
            parsed = parse_skill_md(text)
            _CACHE[key] = parsed
    except (OSError, SkillError, ValueError) as exc:
        version = None
        try:
            version = skill_file.stat().st_mtime_ns
        except OSError:
            pass
        _warn_once(
            ("malformed", str(skill_file), version),
            "Agent skill %r is not offered: %s %s",
            spec.name,
            skill_file,
            exc,
        )
        return None

    frontmatter, instructions = parsed
    declared = frontmatter.get("name")
    if isinstance(declared, str) and declared.strip() and declared.strip() != spec.name:
        _warn_once(
            ("name", str(skill_file), stat.st_mtime_ns),
            "Agent skill %r: SKILL.md names itself %r; the registry name is used",
            spec.name,
            declared,
        )

    return LoadedSkill(
        spec=spec,
        description=_short_description(frontmatter["description"]),
        instructions=instructions,
        references=list_references(spec, folder),
    )


def available_skills(surface: str, root: Path | None = None) -> list[LoadedSkill]:
    """Every skill offered on a surface that loads cleanly right now.

    Args:
        surface: ``chat``, ``chart`` or ``voice``.
        root: Repository root. Defaults to :data:`REPO_ROOT`.

    Returns:
        The loaded skills, in registry order. A skill that fails to load is
        left out.
    """
    loaded = (load_skill(spec, root) for spec in registry.skills_for_surface(surface))
    return [skill for skill in loaded if skill is not None]


def read_reference(skill: LoadedSkill, reference_path: str, root: Path | None = None) -> str:
    """Read one reference page of a skill.

    Args:
        skill: The loaded skill.
        reference_path: A path relative to the skill folder, such as
            ``reference/library.md``. A bare file name is accepted when exactly
            one reference has that name.
        root: Repository root. Defaults to :data:`REPO_ROOT`.

    Returns:
        The page's text.

    Raises:
        SkillError: The path is not one of the skill's reference files, or the
            file cannot be read. The message lists what is available.
    """
    folder = skill_dir(skill.spec, root)
    if folder is None:
        raise SkillError(f"The {skill.name} skill folder is missing on this server.")

    requested = (reference_path or "").strip().replace("\\", "/")
    while requested.startswith("./"):
        requested = requested[2:]
    relative = PurePosixPath(requested)
    refused = (
        not requested
        or relative.is_absolute()
        or ".." in relative.parts
        or ":" in requested
        or _is_hidden(relative)
    )
    if not refused and len(relative.parts) == 1:
        # A bare file name, resolved against the listing so it can only ever
        # name something the listing already vetted.
        matches = [ref for ref in skill.references if PurePosixPath(ref).name == requested]
        if len(matches) == 1:
            relative = PurePosixPath(matches[0])
        else:
            refused = True

    if not refused:
        refused = relative.parts[
            0
        ] not in skill.spec.reference_dirs or relative.suffix.lower() not in {
            suffix.lower() for suffix in skill.spec.reference_suffixes
        }

    if not refused:
        candidate = folder / Path(*relative.parts)
        try:
            resolved = candidate.resolve()
            refused = not resolved.is_relative_to(folder) or not resolved.is_file()
        except OSError:
            refused = True

    if refused:
        raise SkillError(
            f"{reference_path!r} is not a reference page of the {skill.name} skill. "
            "Pass one of its reference paths exactly as listed."
        )

    return _read_text(resolved)
