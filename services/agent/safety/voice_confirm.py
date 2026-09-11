"""Spoken approval for a staged order, decided without a model.

The `/agent` voice surface lets an operator approve a paused order by saying a
word. This module decides whether they did. It is the same shape as
:mod:`services.agent.safety.risk` and for the same reason: a control that can be
talked out of is not a control.

**Nothing here reads a prompt, holds state, or imports anything.** A transcript
string goes in and a boolean comes out, so no phrasing in a conversation, a
symbol name, a broker rejection or a web page can change a verdict. The risk
guard still runs after this, inside the tool body, before the service call.

The order phrase is not the agent's name
---------------------------------------

Two separate values are configured, and keeping them separate is the control:

* **The wake phrase** is how a trader addresses the agent all day. It may be
  several words and it carries no authority whatsoever.
* **The order phrase** does one thing only. It is never a greeting, never a
  name, and is spoken solely to approve an order that has already been staged
  and read back.

:func:`normalise_order_phrase` refuses an order phrase that appears anywhere in
the wake phrase, so an operator cannot collapse the two back into one by
configuration.

Even reserved, the phrase is matched as **the word and nothing else**, allowing
only bare affirmation around it, because a reserved word still gets said::

    is_approval("milo", "milo")                      -> True
    is_approval("yes milo", "milo")                  -> True
    is_approval("milo, confirm.", "milo")            -> True
    is_approval("milo what is bank nifty", "milo")   -> False
    is_approval("place it milo", "milo")             -> False
    is_approval("yes", "milo")                       -> False

The last one matters as much as the rest: a bare affirmation is not approval,
because "yes" is what a trader says to a colleague. Only the configured phrase
approves.

What this does not defend against
---------------------------------

A bare utterance of the order phrase by anyone within earshot while a window is
open will approve the staged order. Reserving the phrase, the alone-word rule,
the short single-use window in the caller, and the on-screen card reduce that
surface; they do not remove it. An operator who wants it removed leaves
`voice_trading_enabled` off.
"""

from __future__ import annotations

import re

__all__ = [
    "AFFIRMATIONS",
    "MAX_PHRASE_LENGTH",
    "MAX_WAKE_LENGTH",
    "MIN_PHRASE_LENGTH",
    "is_approval",
    "normalise_order_phrase",
    "normalise_wake_phrase",
    "window_is_open",
]

#: Bare affirmations permitted alongside the word. Nothing here approves on its
#: own; each may only accompany the configured name.
AFFIRMATIONS: frozenset[str] = frozenset(
    {"yes", "yeah", "yep", "yup", "ok", "okay", "confirm", "confirmed", "please", "sure"}
)

#: An approval is at most this many words. Three covers "yes milo confirm" and
#: refuses anything that has started to become a sentence.
_MAX_TOKENS = 3

MIN_PHRASE_LENGTH = 3
MAX_PHRASE_LENGTH = 20
MAX_WAKE_LENGTH = 40

#: The order phrase is letters only and one word. A digit or a hyphen does not
#: survive transcription intact, and a space cannot satisfy the alone-word rule.
_PHRASE_PATTERN = re.compile(rf"^[A-Za-z]{{{MIN_PHRASE_LENGTH},{MAX_PHRASE_LENGTH}}}$")

#: The wake phrase carries no authority, so it may be several words.
_WAKE_PATTERN = re.compile(rf"^[A-Za-z][A-Za-z ]{{0,{MAX_WAKE_LENGTH - 1}}}$")

#: Everything that is not a letter is separator. Transcripts arrive with commas,
#: full stops and the occasional dash, none of which carry meaning here.
_TOKEN_PATTERN = re.compile(r"[A-Za-z]+")


def normalise_wake_phrase(raw: object) -> str:
    """Validate the phrase a trader uses to address the agent.

    This value has no security role at all. It is validated only so it survives
    transcription and renders sensibly in the UI.

    Args:
        raw: The operator's input.

    Returns:
        The phrase with its capitalisation preserved and internal whitespace
        collapsed to single spaces.

    Raises:
        ValueError: If the value is empty, over-long, or carries anything but
            letters and spaces.
    """
    phrase = " ".join(str(raw or "").split())
    if not _WAKE_PATTERN.match(phrase):
        raise ValueError(
            "The wake phrase must be letters and spaces only, at most "
            f"{MAX_WAKE_LENGTH} characters."
        )
    return phrase


def normalise_order_phrase(raw: object, wake_phrase: object = "") -> str:
    """Validate the phrase that approves a staged order.

    Args:
        raw: The operator's input.
        wake_phrase: The configured wake phrase, so the two can be kept apart.
            Passing nothing skips that check, which is only correct when the
            caller has no wake phrase to compare against.

    Returns:
        The phrase, lower-cased, since it is matched case-insensitively and
        never displayed as a name.

    Raises:
        ValueError: If the value is not a single run of between
            :data:`MIN_PHRASE_LENGTH` and :data:`MAX_PHRASE_LENGTH` letters, or
            if it also appears in the wake phrase. The second check is what
            stops an operator collapsing the two values back into one: a word
            said to get the agent's attention must not also place a trade.
    """
    phrase = str(raw or "").strip()
    if not _PHRASE_PATTERN.match(phrase):
        raise ValueError(
            "The order approval phrase must be a single word of "
            f"{MIN_PHRASE_LENGTH} to {MAX_PHRASE_LENGTH} letters, with no "
            "spaces, digits or punctuation."
        )
    phrase = phrase.lower()
    wake_tokens = {token.lower() for token in _TOKEN_PATTERN.findall(str(wake_phrase or ""))}
    if phrase in wake_tokens:
        raise ValueError(
            "The order approval phrase must not appear in the wake phrase. "
            "A word said to get the agent's attention must not also be the "
            "word that places an order."
        )
    return phrase


def is_approval(transcript: object, order_phrase: object) -> bool:
    """Whether one spoken utterance approves a staged order.

    Args:
        transcript: What the speech model heard. Punctuation and casing are
            irrelevant; anything that is not a letter is treated as a separator.
        order_phrase: The configured approval phrase, as stored.

    Returns:
        ``True`` only when the utterance consists of the configured phrase,
        optionally accompanied by bare affirmations from :data:`AFFIRMATIONS`,
        and nothing else. Any other content, including a sentence that happens
        to contain the phrase, returns ``False``.
    """
    try:
        word = normalise_order_phrase(order_phrase).lower()
    except ValueError:
        # An unusable configured phrase approves nothing. Failing closed here
        # means a malformed settings row cannot become a permissive matcher.
        return False

    tokens = [token.lower() for token in _TOKEN_PATTERN.findall(str(transcript or ""))]
    if not tokens or len(tokens) > _MAX_TOKENS:
        return False
    if word not in tokens:
        return False
    return all(token == word or token in AFFIRMATIONS for token in tokens)


def window_is_open(opened_at: float | None, now: float, seconds: int) -> bool:
    """Whether a spoken approval window is still open.

    Separate from :func:`is_approval` so a caller cannot accidentally satisfy
    one test and skip the other: both must pass, and they fail for different
    reasons.

    Args:
        opened_at: Monotonic timestamp when the order was read back, or ``None``
            when no order is staged.
        now: The current monotonic timestamp.
        seconds: The configured window, from ``voice_confirm_window_seconds``.

    Returns:
        ``True`` while the window is open. A missing timestamp, a
        non-positive window, or a clock that has gone backwards all return
        ``False``.
    """
    if opened_at is None or seconds <= 0:
        return False
    elapsed = now - opened_at
    if elapsed < 0:
        return False
    return elapsed <= seconds
