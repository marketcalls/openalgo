"""Attachments on a chat turn: what is accepted, and what it costs.

One turn may carry a few files. Two kinds reach the model and they reach it by
completely different routes, which is the reason this module exists rather than
a helper in the blueprint:

* **An image** goes to the provider as an image part, built here into agno's
  ``Image`` and passed to ``agent.run(images=...)``. Agno's LiteLLM model turns
  each one into ``{"type": "image_url", "image_url": {"url": "data:...;base64,..."}}``
  through ``agno.utils.openai.images_to_message``, so the bytes are base64 on
  the wire twice: once from the browser to us, once from us to the provider.
* **A text file** never becomes a media part at all. It is decoded and folded
  into the message inside an ``<attachment>`` block, because a text file is
  data somebody wrote and every other piece of text that entered the system as
  data goes through the same wrapper.

Three rules this module exists to keep
--------------------------------------

**A model that cannot see refuses the turn, by name.** Not here: this module
reports that an image is present and :func:`services.agent.builder.build_agent`
refuses. What matters is that no path silently drops an image. An operator who
attaches a screenshot and gets a confident answer has no way to tell it was
never looked at, and that is the outcome worth engineering against.

**The bytes decide what a file is.** The declared media type and the filename
are both attacker-influenced, and neither is consulted for the allow decision.
A file is an image because it starts with a PNG, JPEG, GIF or WebP signature,
and it is text because every byte of it decodes as UTF-8 with no control
characters in it. A declared type that contradicts the bytes is refused rather
than reinterpreted: the client is either confused or lying, and quietly picking
the answer we prefer is how a mismatch stops being visible.

**Everything is bounded.** An image is base64 in a JSON body, so it inflates by
about a third on the wire, and then it is charged as input tokens **again on
every later turn of the conversation**, because agno replays the history. The
cost of one image is therefore not paid once. Measured against the configured
model: a 360x130 PNG cost 73 input tokens on its own turn and 70 more on the
next one; a 1920x1080 screenshot cost 2,449 and then 2,447, and goes on costing
that on every turn inside the ``DEFAULT_NUM_HISTORY_RUNS`` window. Note that
neither number tracks the byte count, because a provider charges an image by its
dimensions; the caps below bound bytes because bytes are what this process has
to hold, and the token cost is what the operator has to be told.

Storage
-------
:func:`stored_metadata` is what goes on the ``ag_message`` row: name, sniffed
type, byte count and a short digest. **The bytes are not stored.**

The reference is ``MAX_STORED_VIZ`` in ``blueprints/agent.py``, which caps a
turn at four chart specs on the grounds that "a chart spec is a series, not a
sentence" and an unbounded count would put a data dump in a text column. An
image is a far larger object than a chart spec and would go in the same column,
which is read in full every time the conversation is opened. Measured on this
change: a whole stored user row carrying two attachments is 467 bytes, of which
the metadata is about 120 bytes per file; the image it describes was 2,584
bytes, a 1920x1080 screenshot was 11,140, and the per-file cap is 4,000,000.
The metadata is enough to re-render the composer's chip, which is what the
transcript needs to show: that a file was sent, which one, and how big it was.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from services.agent.prompts import wrap_attachment
from utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from agno.media import Image

logger = get_logger(__name__)

__all__ = [
    "MAX_ATTACHMENTS",
    "MAX_ATTACHMENT_BYTES",
    "MAX_ENCODED_CHARS",
    "MAX_NAME_CHARS",
    "MAX_TEXT_CHARS",
    "MAX_TOTAL_BYTES",
    "Attachment",
    "AttachmentError",
    "has_image",
    "images_for_run",
    "parse_attachments",
    "prompt_block",
    "stored_metadata",
]

# ---------------------------------------------------------------------------
# The caps
#
# Every one of them is enforced before the next byte is decoded, and each says
# what it is protecting. None of them is configurable: this module takes no
# configuration from `.env`, and a limit an operator can raise is a limit that
# gets raised the first time a file does not fit.
# ---------------------------------------------------------------------------

#: Files per turn. A question about a screenshot needs one; a comparison needs
#: two or three. Beyond that the conversation is carrying a directory, and every
#: one of them is replayed into context on every subsequent turn.
MAX_ATTACHMENTS = 4

#: Decoded bytes in one file. A phone screenshot is 200 KB to 2 MB and a full
#: desktop capture is under 4 MB, so this accepts what an operator will actually
#: attach without accepting a video frame dump.
MAX_ATTACHMENT_BYTES = 4_000_000

#: Decoded bytes across the whole turn, which is the number that matters: four
#: files at the per-file cap would otherwise be 16 MB in one request body.
MAX_TOTAL_BYTES = 8_000_000

#: Characters of a text file that reach the prompt. Roughly 5,000 tokens, which
#: is a large fraction of a turn on its own, and the file is replayed on every
#: later turn. Longer files are refused rather than silently truncated: an
#: answer written from the first fifth of a file, with no sign that the rest was
#: dropped, is the same failure as an image that was never looked at.
MAX_TEXT_CHARS = 20_000

#: Characters of a filename that are kept. The name is an attribute in the
#: prompt and a label in the transcript, never a path and never opened.
MAX_NAME_CHARS = 120

#: Ceiling on the base64 string, checked before decoding so a 100 MB payload is
#: refused without being materialised a second time. Base64 is 4 characters per
#: 3 bytes; the slack covers padding, a data-URL prefix and any embedded
#: whitespace.
MAX_ENCODED_CHARS = (MAX_ATTACHMENT_BYTES * 4) // 3 + 4096

# ---------------------------------------------------------------------------
# Sniffing
# ---------------------------------------------------------------------------

#: Magic-byte prefixes for the image types that are accepted. Prefix matching
#: only: nothing here decodes an attacker-supplied image, because a decoder is a
#: far larger attack surface than a byte comparison and no decision needs the
#: pixels.
_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

#: WebP is the one that is not a plain prefix: ``RIFF`` then a four byte size
#: then ``WEBP``.
_WEBP_HEAD = b"RIFF"
_WEBP_TAG = b"WEBP"

#: Formats that are definitely not text and are definitely not an image this
#: module accepts, named so the refusal says something useful. A PDF is the one
#: that needs this: its first bytes are plain ASCII, so without it a PDF would
#: be refused only once the reader reached the binary further in, and a short
#: one would be accepted as a text file whose entire content is ``%PDF-1.7``.
#: An operator will try a PDF, and "attach a text file instead" is a better
#: answer than the model summarising a version header.
_REJECTED_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "a PDF"),
    (b"PK\x03\x04", "a zip or Office document"),
    (b"\x1f\x8b", "a gzip archive"),
    (b"Rar!\x1a\x07", "a RAR archive"),
    (b"7z\xbc\xaf\x27\x1c", "a 7-Zip archive"),
    (b"\x7fELF", "an executable"),
    (b"MZ", "an executable"),
    (b"%!PS", "a PostScript file"),
)

MIME_TEXT = "text/plain"

#: What "the client does not know what this is" looks like. An operating system
#: that cannot name a file says ``application/octet-stream``, which is not a
#: claim about the content and so cannot contradict one.
_UNDECLARED: frozenset[str] = frozenset({"", "application/octet-stream"})

#: Media types a client may declare for a file whose bytes sniff as text. A CSV,
#: a JSON export and a Markdown note are all text, and refusing them for their
#: label when their bytes are plainly text would be pedantry rather than safety.
_TEXT_DECLARATIONS: frozenset[str] = frozenset(
    {
        "text/plain",
        "text/csv",
        "text/markdown",
        "text/x-markdown",
        "text/tab-separated-values",
        "text/x-python",
        "text/xml",
        "text/html",
        "application/json",
        "application/x-ndjson",
        "application/xml",
        "application/csv",
    }
)

#: ``image/jpg`` is not a registered type but browsers and operating systems
#: emit it, and refusing a JPEG for spelling its own name the common way would
#: be a bug report rather than a defence.
_MIME_ALIASES: dict[str, str] = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg"}

#: Control characters that mean a file is not text. Tab, newline and carriage
#: return are excluded because a text file has them; everything else in C0, and
#: the C1 range, is a binary that happened to decode.
_NOT_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

#: ``data:image/png;base64,`` and friends. The browser's ``readAsDataURL``
#: produces one, so accepting it saves every client the same split.
_DATA_URL = re.compile(r"\Adata:([A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+)?;base64,", re.I)


class AttachmentError(ValueError):
    """An attachment was refused, with a message written for the operator.

    Attributes:
        message: Why it was refused, naming the file. Safe to return in an HTTP
            body: it never carries file content, only the file's own label and
            the measured facts about it.
    """

    def __init__(self, message: str) -> None:
        """Store the message on the exception as well as in its args."""
        super().__init__(message)
        self.message = message


@dataclass(frozen=True, slots=True)
class Attachment:
    """One accepted file.

    Frozen because an attachment crosses into the run thread with the rest of
    the turn and nothing may change it after it was measured and allowed.

    Attributes:
        name: The filename as the client sent it, trimmed to
            :data:`MAX_NAME_CHARS` and stripped of anything path-like. A label,
            never a path: nothing in this module opens a file.
        kind: ``image`` or ``text``, decided by the bytes.
        mime: The media type the bytes sniff as.
        declared: The media type the client declared, kept for the record and
            for the refusal message. It decides nothing.
        size: Decoded byte count.
        digest: First 12 hex characters of the SHA-256 of the bytes. Enough to
            recognise the same file attached twice, and to match a stored chip
            against a file on disk, without keeping the file.
        data: The image bytes. Empty for a text attachment.
        text: The decoded text. Empty for an image.
    """

    name: str
    kind: str
    mime: str
    declared: str
    size: int
    digest: str
    data: bytes = b""
    text: str = ""


def _clean_name(value: Any, index: int) -> str:
    """Reduce a client-supplied filename to a safe label.

    Args:
        value: Whatever the client sent as ``name``.
        index: Position in the list, used when there is no usable name.

    Returns:
        A single-line label of at most :data:`MAX_NAME_CHARS` characters. Path
        separators are dropped rather than escaped, because the value is only
        ever displayed and interpolated into a prompt attribute, and a name that
        still looks like a path invites a later reader to treat it as one.
    """
    text = "" if value is None else str(value)
    text = text.replace("\\", "/").rsplit("/", 1)[-1]
    text = _NOT_TEXT.sub("", text).replace("\n", " ").replace("\r", " ").strip()
    return text[:MAX_NAME_CHARS] or f"attachment-{index + 1}"


def _clean_mime(value: Any) -> str:
    """Normalise a declared media type.

    Args:
        value: Whatever the client sent as ``mime``, possibly with parameters.

    Returns:
        The lower-case type without parameters, aliases resolved, or an empty
        string when the client declared nothing.
    """
    text = "" if value is None else str(value)
    text = text.split(";", 1)[0].strip().lower()
    return _MIME_ALIASES.get(text, text)


def _sniff(data: bytes) -> tuple[str, str]:
    """Decide what a file is from its bytes alone.

    Args:
        data: The decoded file.

    Returns:
        ``(kind, mime)`` where kind is ``image`` or ``text``.

    Raises:
        AttachmentError: The bytes are neither an allowed image nor text.
    """
    for signature, mime in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return "image", mime
    if len(data) >= 12 and data[:4] == _WEBP_HEAD and data[8:12] == _WEBP_TAG:
        return "image", "image/webp"

    for signature, description in _REJECTED_SIGNATURES:
        if data.startswith(signature):
            raise AttachmentError(
                f"is {description}, which is not supported. Attach a PNG, JPEG, GIF or "
                "WebP image, or a text file."
            )

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise AttachmentError(
            "is not a supported file. Attach a PNG, JPEG, GIF or WebP image, or a text file."
        ) from None
    if _NOT_TEXT.search(text):
        raise AttachmentError(
            "is not a supported file. Attach a PNG, JPEG, GIF or WebP image, or a text file."
        )
    return "text", MIME_TEXT


def _check_declaration(kind: str, sniffed: str, declared: str) -> None:
    """Refuse a declared media type that the bytes contradict.

    The bytes have already decided. This exists because a contradiction means
    the client is confused or lying about the file, and silently going with the
    bytes would make that invisible: a build that renames every upload to
    ``image/png`` would look like it worked right up until the day the rename
    was wrong about something that mattered.

    Args:
        kind: ``image`` or ``text``, from :func:`_sniff`.
        sniffed: The media type the bytes are.
        declared: The media type the client said, already normalised.

    Raises:
        AttachmentError: The declaration and the bytes disagree.
    """
    if declared in _UNDECLARED:
        return
    if kind == "image":
        if declared != sniffed:
            raise AttachmentError(
                f"was sent as {declared} but its bytes are {sniffed}. "
                "Send the file with its real type."
            )
        return
    if declared not in _TEXT_DECLARATIONS:
        raise AttachmentError(
            f"was sent as {declared} but its bytes are plain text. "
            "Send the file with its real type."
        )


def _decode(raw: Any) -> tuple[bytes, str]:
    """Decode one attachment's payload, refusing before it is materialised.

    Args:
        raw: The ``data`` field: base64, optionally as a ``data:`` URL.

    Returns:
        ``(bytes, mime_from_data_url)``. The second value is a declaration like
        any other and is only used when the client sent no ``mime`` field.

    Raises:
        AttachmentError: The payload is missing, too long, or not base64.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise AttachmentError("carries no data.")

    payload = raw.strip()
    inline_mime = ""
    match = _DATA_URL.match(payload)
    if match:
        inline_mime = _clean_mime(match.group(1))
        payload = payload[match.end() :]

    # Before the decode, not after. Base64 is 4 characters per 3 bytes, so a
    # payload longer than this cannot fit under the byte cap and decoding it
    # would put a second copy of an oversized string in memory to learn that.
    if len(payload) > MAX_ENCODED_CHARS:
        raise AttachmentError(
            f"is larger than the {MAX_ATTACHMENT_BYTES // 1000} kB limit for one file."
        )

    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise AttachmentError("is not valid base64.") from None
    if not data:
        raise AttachmentError("is empty.")
    return data, inline_mime


def parse_attachments(raw: Any) -> list[Attachment]:
    """Validate a turn's attachments and return the accepted ones.

    Called before the conversation row is created, so a refused attachment
    leaves nothing behind.

    Args:
        raw: The request body's ``attachments`` field. ``None`` and an empty
            list both mean no attachments.

    Returns:
        The attachments, in the order they were sent.

    Raises:
        AttachmentError: Any of them was refused. The whole turn is refused
            rather than the offending file being dropped, because a turn that
            silently went out without the file the question was about is the
            failure this module exists to prevent.
    """
    if raw is None or raw == []:
        return []
    if not isinstance(raw, list):
        raise AttachmentError("attachments must be a list.")
    if len(raw) > MAX_ATTACHMENTS:
        raise AttachmentError(
            f"A turn may carry at most {MAX_ATTACHMENTS} attachments; {len(raw)} were sent."
        )

    accepted: list[Attachment] = []
    total = 0
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise AttachmentError(f"Attachment {index + 1} must be a JSON object.")
        name = _clean_name(item.get("name"), index)

        try:
            data, inline_mime = _decode(item.get("data"))
            if len(data) > MAX_ATTACHMENT_BYTES:
                raise AttachmentError(
                    f"is {len(data) // 1000} kB, over the "
                    f"{MAX_ATTACHMENT_BYTES // 1000} kB limit for one file."
                )
            kind, mime = _sniff(data)
            declared = _clean_mime(item.get("mime")) or inline_mime
            _check_declaration(kind, mime, declared)
        except AttachmentError as exc:
            # The file's own label is prefixed here rather than at every raise,
            # so each check states one fact and this states which file it is
            # about.
            raise AttachmentError(f"{name} {exc.message}") from None

        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise AttachmentError(
                f"The attachments total more than the {MAX_TOTAL_BYTES // 1000} kB "
                "limit for one turn."
            )

        text = ""
        if kind == "text":
            text = data.decode("utf-8")
            if len(text) > MAX_TEXT_CHARS:
                raise AttachmentError(
                    f"{name} is {len(text)} characters, over the {MAX_TEXT_CHARS} character "
                    "limit for a text attachment. Attach a shorter extract."
                )

        accepted.append(
            Attachment(
                name=name,
                kind=kind,
                mime=mime,
                declared=declared,
                size=len(data),
                digest=hashlib.sha256(data).hexdigest()[:12],
                data=data if kind == "image" else b"",
                text=text,
            )
        )

    logger.info(
        "Agent turn carries %s attachment(s): %s",
        len(accepted),
        ", ".join(f"{a.name} {a.mime} {a.size}B" for a in accepted),
    )
    return accepted


def has_image(attachments: Sequence[Attachment]) -> bool:
    """Whether the turn carries at least one image.

    Args:
        attachments: The accepted attachments.

    Returns:
        True when a vision-capable model is required for this turn.
    """
    return any(item.kind == "image" for item in attachments)


def images_for_run(attachments: Sequence[Attachment]) -> list[Image]:
    """Build agno's image objects for ``agent.run(images=...)``.

    Agno is imported here rather than at module level so this module stays
    importable without the optional dependency, which is the same reason
    ``tools/__init__.py`` imports it inside its factory.

    Args:
        attachments: The accepted attachments. Text ones are skipped.

    Returns:
        One ``agno.media.Image`` per image attachment, carrying raw bytes and
        the sniffed media type. ``content`` rather than ``url`` or ``filepath``:
        a URL would have agno fetch it server-side, and a path would mean this
        process wrote an operator's file to disk to read it straight back.
    """
    from agno.media import Image as AgnoImage

    return [
        AgnoImage(content=item.data, mime_type=item.mime, format=item.mime.split("/", 1)[-1])
        for item in attachments
        if item.kind == "image"
    ]


def prompt_block(attachments: Sequence[Attachment]) -> str:
    """Render the text attachments as untrusted blocks for the model.

    Args:
        attachments: The accepted attachments. Image ones are skipped, because
            an image travels as a media part rather than as prompt text.

    Returns:
        The blocks joined by blank lines, or an empty string when the turn
        carries no text file.
    """
    blocks = [
        wrap_attachment(item.name, item.text, media_type=item.mime, bytes=item.size)
        for item in attachments
        if item.kind == "text"
    ]
    return "\n\n".join(blocks)


def stored_metadata(attachments: Sequence[Attachment]) -> list[dict[str, Any]]:
    """What is persisted on the ``ag_message`` row.

    Args:
        attachments: The accepted attachments.

    Returns:
        One small mapping per file. No bytes and no text: see this module's own
        docstring for why, and for the size comparison that decided it.
    """
    return [
        {
            "name": item.name,
            "kind": item.kind,
            "mime": item.mime,
            "size": item.size,
            "digest": item.digest,
        }
        for item in attachments
    ]
