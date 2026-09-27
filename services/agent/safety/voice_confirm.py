"""Spoken approval for a staged order, decided without a model.

The `/agent` voice surface lets an operator approve a paused order by answering
out loud. This module decides whether they did. It is the same shape as
:mod:`services.agent.safety.risk` and for the same reason: a control that can be
talked out of is not a control.

**Nothing here reads a prompt, holds state, or imports anything.** A transcript
string goes in and a boolean comes out, so no phrasing in a conversation, a
symbol name, a broker rejection or a web page can change a verdict. The risk
guard still runs after this, inside the tool body, before the service call.

What protects an order here
---------------------------

The read-back. Before anything can be approved, the order is spoken back in
full - action, quantity, the contract as a person says it, the exchange, the
product and the order type - and the trader answers a question they have just
heard the whole of.

There is no secret word. A password was tried and removed: it made every
approval a memory test, it was read aloud by the speech model until that was
fixed, and it was written into the audit trail every time it was spoken. What
it bought was narrow - a stranger within earshot cannot say a word they do not
know - and what it cost was the thing traders actually do, which is answer.

So this is honest about its limit: **anyone within earshot who says yes while
the window is open approves the staged order, and the agent cannot tell one
voice from another.** The window is short and single use, the order has just
been read back, and every limit in the risk guard still applies afterwards. An
operator who does not control the room they trade in leaves
`voice_trading_enabled` off and taps the card.
"""

from __future__ import annotations

import re

__all__ = [
    "CONFIRMATIONS",
    "is_spoken_confirmation",
    "MAX_WAKE_LENGTH",
    "normalise_wake_phrase",
    "window_is_open",
]

#: Bare affirmations permitted alongside the word. Nothing here approves on its
#: own; each may only accompany the configured name.
#: Words that, on their own, mean yes to an order that has just been read back.
#:
#: Short and closed on purpose. Anything longer is a sentence, and a sentence
#: near a pending order is conversation rather than an answer to it.
CONFIRMATIONS: frozenset[str] = frozenset(
    {
        "yes",
        "yeah",
        "yep",
        "yup",
        "ok",
        "okay",
        "confirm",
        "confirmed",
        "place",
        "send",
        "go",
        "ahead",
        "do",
        "it",
        "please",
        "sure",
        "right",
        "correct",
    }
)

#: A confirmation is at most this many words. "yes go ahead please" is four.
_MAX_CONFIRMATION_TOKENS = 4

MAX_WAKE_LENGTH = 40

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


def is_spoken_confirmation(transcript: object) -> bool:
    """Whether one utterance is a plain yes to an order already read back.

    The operator's chosen way of approving: the order is spoken back in full -
    action, quantity, contract, exchange, product, order type - and the trader
    answers the way a person answers, without a password.

    **The read-back is what protects this.** There is no secret here: anyone
    within earshot who says yes while the window is open approves the staged
    order, and the agent cannot tell one voice from another. What it buys is
    that a trader who has just heard the order in full says one natural word
    rather than remembering a token. An operator who does not control the room
    they trade in should set the approval mode to `phrase` instead.

    Every other guard is unchanged: both switches, the window, and the risk
    guard inside the tool body, which reads no prompt and applies every limit
    after any approval::

        is_spoken_confirmation("yes")            -> True
        is_spoken_confirmation("go ahead")       -> True
        is_spoken_confirmation("yes place it")   -> True
        is_spoken_confirmation("no")             -> False
        is_spoken_confirmation("yes but wait")   -> False
        is_spoken_confirmation("what is nifty")  -> False

    Args:
        transcript: What the speech model heard.

    Returns:
        True when every word is an affirmation and there are not too many of
        them. Anything carrying other content is conversation, not an answer.
    """
    tokens = [token.lower() for token in _TOKEN_PATTERN.findall(str(transcript or ""))]
    if not tokens or len(tokens) > _MAX_CONFIRMATION_TOKENS:
        return False
    return all(token in CONFIRMATIONS for token in tokens)
