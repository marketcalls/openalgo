"""The voice surface: minting a `gpt-live-1` session, and speaking briefly.

This is the only module in the codebase that knows a speech vendor exists.
Everything above it - the blueprint, the toolkits, the risk guard, the audit -
deals in surfaces and transcripts, so replacing the vendor is a change here and
nowhere else.

What this module does not do
----------------------------

**It does not carry audio.** The browser holds the WebRTC connection directly
with OpenAI. The server's entire involvement is one outbound POST that swaps the
browser's SDP offer for an answer. There is no socket to keep, no thread, no
event loop, and nothing to reap, which is what keeps the voice surface clear of
the eventlet hazards documented in `CLAUDE.md`.

**It does not think.** The session is minted in *client delegation* mode, so
`gpt-live-1` performs no reasoning of its own: when it hears something needing
an answer it raises `session.delegation.created` and waits. The answer comes
from the same agno agent on LiteLLM that serves the text surface, which is why
an operator running their intelligence on Claude, or on a local Ollama model,
keeps it when they turn the microphone on.

**It does not approve anything.** Spoken approval is decided by
:mod:`services.agent.safety.voice_confirm`, a pure function that reads no
prompt.

Egress
------

:data:`LIVE_SESSIONS_URL` is a module constant and is never taken from a
request. The voice surface therefore adds no base-URL override and stays off the
SSRF surface described in `docs/design/55-agent/README.md`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "LIVE_SESSIONS_URL",
    "SPEAKABLE_CHAR_BUDGET",
    "VoiceProbe",
    "VoiceUnavailable",
    "build_instructions",
    "mint_session",
    "probe",
    "speakable",
]

#: Kept for callers that predate the provider vocabulary. The live value comes
#: from the configured provider's spec, which is equally a module constant and
#: equally never taken from a request.
LIVE_SESSIONS_URL = "https://api.openai.com/v1/live/sessions"

#: The session mint is one round trip against a vendor that is usually quick and
#: occasionally is not. Long enough to survive a slow handshake, short enough
#: that a wedged vendor does not hold a greenlet for a minute.
MINT_TIMEOUT_SECONDS = 20.0

#: `session.commentary.append` caps content at 500 tokens. This budget is well
#: inside that, because the real constraint is not the API limit but how much a
#: person will sit through before interrupting.
SPEAKABLE_CHAR_BUDGET = 480


#: Said whenever the cause is an empty account, wherever it surfaces from.
_NO_CREDIT = (
    "Your OpenAI account has no credits left, so the voice session could not "
    "be started. Add credits at platform.openai.com under billing. Everything "
    "else in the agent keeps working if it runs on a different provider."
)


class VoiceUnavailable(RuntimeError):
    """The voice surface cannot start, with a reason an operator can act on."""


@dataclass(frozen=True)
class VoiceProbe:
    """The result of testing the stored voice key.

    Attributes:
        ok: Whether a session was minted.
        message: What to show the operator, in plain words.
        latency_ms: How long the vendor took.
        model: The model the test asked for.
    """

    ok: bool
    message: str
    latency_ms: int
    model: str = ""


def build_instructions(agent_name: str, *, trading: bool) -> str:
    """The instructions the speech model is given about how to behave.

    These govern **delivery only**. Nothing here decides anything: the model
    they are handed to has no tools, no data and no authority, and every answer
    it speaks was produced by the agent behind it.

    Args:
        agent_name: What the trader calls the agent.
        trading: Whether mutating tools are reachable on this surface at all.
            When False the phrase is never mentioned, because offering an
            reading an order back for a capability that is switched off would
            describe something that cannot happen.

    Returns:
        The instructions string.
    """
    lines = [
        f"You are {agent_name}, the spoken voice of a trading assistant.",
        "",
        "You have no data, no tools and no access to anything. You cannot see a",
        "price, a position, an order or an account, and you have no way to place",
        "or change anything. Everything you say about any of those was handed to",
        "you by the assistant behind you.",
        "",
        "So: hand over every request. A question about the market, an",
        "instrument, the account, a position or an order goes to the assistant,",
        "always, even when you believe you know the answer and even when the",
        "trader is only refining something they said a moment ago. Do not answer",
        "it yourself, do not say what you think the answer is, and do not tell",
        "the trader what you are about to do instead of doing it.",
        "",
        "Never describe an order as placed, staged, prepared, being set up or",
        "waiting unless the assistant has told you that it is. Saying so when it",
        "is not leaves a trader believing a trade exists when none does, which",
        "is the worst thing you can do.",
        "",
        "While you are waiting for the assistant, say so plainly and briefly.",
        "",
        "How to speak:",
        "- One or two sentences. The detail is already on the trader's screen.",
        "- Round numbers for the ear. Say twenty-three thousand four hundred,",
        "  not twenty-three thousand four hundred and twelve point five five.",
        "- Never read out markdown, tables or bullet lists.",
        "- If work is still running, say so briefly rather than going silent.",
        "",
        "Instrument names:",
        "- Never spell a contract out character by character. NIFTY28MAR2420800CE",
        "  is said as 'the twenty thousand eight hundred Nifty call expiring on",
        "  the twenty-eighth of March', never as 'N I F T Y two eight M A R'.",
        "- BANKNIFTY24APR24FUT is 'the April Bank Nifty future'.",
        "- A decimal strike is spoken as a number: 292.5 is 'two ninety-two",
        "  point five'.",
        "- Exchange codes are spoken as a trader says them. NFO is 'NSE F and O',",
        "  NSE_INDEX is 'the NSE index'. Never say the underscore.",
        "- Product and order types are spoken in words: CNC is delivery, NRML is",
        "  normal, MIS is intraday, SL-M is 'stop loss market'.",
    ]
    if trading:
        lines += [
            "",
            "Orders:",
            "- You never place an order and you never decide that one is safe.",
            "- When an order is staged, read it back in full - action, quantity,",
            "  the contract said as a person would say it, the exchange, the",
            "  product and the order type - and then ask the trader to confirm.",
            "  The read-back is the only thing standing between a misheard order",
            "  and a real one, so never shorten or summarise it.",
            "- Read back exactly what you were given. Never round a quantity,",
            "  never simplify a contract into a nearer-sounding one, and never",
            "  fill in an expiry or a strike that was not in what you were given.",
        ]
    return "\n".join(lines)


def _session_payload(offer_sdp: str, config: dict[str, Any], instructions: str) -> dict[str, Any]:
    """The request body for one minted session.

    Args:
        offer_sdp: The browser's SDP offer.
        config: The voice configuration, as `settings.get_voice_config` returns.
        instructions: What the speech model is told about delivery.

    Returns:
        The JSON body.
    """
    from services.agent.voice_providers import voice_provider_spec

    spec = voice_provider_spec(config.get("voice_provider") or "openai")
    return {
        "session": {
            "model": str(config.get("voice_model") or spec.default_model),
            "instructions": instructions,
            "audio": {"output": {"voice": str(config.get("voice_speaker") or spec.speakers[0])}},
            # The mode in which the speech model answers nothing on its own.
            # Every question it hears comes back as session.delegation.created.
            "delegation": dict(spec.delegation),
        },
        "transport": {"type": "webrtc", "sdp": offer_sdp},
    }


def mint_session(offer_sdp: Any, config: dict[str, Any] | None = None) -> str:
    """Swap the browser's SDP offer for the vendor's answer.

    Args:
        offer_sdp: The browser's offer, as `application/sdp` text.
        config: The voice configuration. Read fresh when not supplied.

    Returns:
        The answer SDP, for the browser to apply as its remote description.

    Raises:
        VoiceUnavailable: When voice is switched off, no key is stored, the
            offer is unusable, or the vendor refused. The message is safe to
            show an operator and never carries the key.
    """
    from services.agent import settings

    offer = str(offer_sdp or "").lstrip()
    if not offer.startswith("v="):
        raise VoiceUnavailable("That is not a usable connection offer.")
    # SDP is a CRLF-terminated format and the parser at the other end means it:
    # an offer whose final line has been stripped of its terminator comes back
    # as "failed to unmarshal SDP: EOF". Normalising here rather than trusting
    # the caller covers both the browser body and the probe constant.
    offer = offer.replace("\r\n", "\n").rstrip("\n").replace("\n", "\r\n") + "\r\n"

    config = config or settings.get_voice_config()
    if not config.get("voice_enabled"):
        raise VoiceUnavailable("The voice agent is switched off in agent configuration.")

    key = settings.voice_key()
    if not key:
        raise VoiceUnavailable("No OpenAI key is stored for the voice agent.")

    instructions = build_instructions(
        str(config.get("voice_agent_name") or "Vega"),
        trading=bool(config.get("trading_effective")),
    )
    from services.agent.voice_providers import voice_provider_spec

    spec = voice_provider_spec(config.get("voice_provider") or "openai")
    payload = _session_payload(offer, config, instructions)

    try:
        client = get_httpx_client()
        response = client.post(
            spec.sessions_url,
            headers={"Authorization": f"Bearer {key}"},
            json=payload,
            timeout=MINT_TIMEOUT_SECONDS,
        )
        if response.status_code >= 500:
            # Once, and only for a 5xx. A session that was not created was not
            # billed, and the alternative is asking a trader to press the
            # microphone again for a blip that has usually already passed. A
            # 4xx is never retried: it will fail the same way and the message
            # is the useful part.
            logger.warning("Voice provider returned %s; retrying once", response.status_code)
            response = client.post(
                spec.sessions_url,
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
                timeout=MINT_TIMEOUT_SECONDS,
            )
    except Exception:
        # No traceback: this frame's locals held the key.
        logger.error("Could not reach the voice provider")
        raise VoiceUnavailable("Could not reach the voice provider.") from None
    finally:
        key = ""

    if response.is_error:
        logger.error("Voice provider refused the session: HTTP %s", response.status_code)
        raise VoiceUnavailable(_refusal_message(response.status_code, response.text))

    try:
        answer = response.json()["transport"]["sdp"]
    except Exception:
        logger.exception("Voice provider returned an unusable session")
        raise VoiceUnavailable("The voice provider returned something unusable.") from None

    try:
        from database import agent_db

        agent_db.mark_secret_used(settings.voice_secret_name())
    except Exception:
        logger.exception("Could not record voice key usage")

    return str(answer)


def _refusal_message(status: int, body: str) -> str:
    """Turn a vendor refusal into something an operator can act on.

    The body is read for a message but never echoed wholesale, because a vendor
    error can carry request detail that has no business on a settings screen.

    Args:
        status: The HTTP status.
        body: The response body.

    Returns:
        A plain-language message.
    """
    if status in (401, 403):
        return "The OpenAI key for the voice agent was rejected."
    if status == 404:
        return "The configured voice model is not available on that key."
    if status == 429:
        # Out of credit and rate limited share a status code and do not share a
        # fix, so the body decides which sentence an operator gets.
        if "insufficient_quota" in body or "credit" in body.lower():
            return _NO_CREDIT
        return "The voice provider is rate limiting this key. Try again shortly."
    if status >= 500:
        # **An exhausted balance arrives here.** Observed: an account with no
        # credits left got a bare "Internal Server Error" with no JSON from this
        # endpoint, while `/v1/chat/completions` on the same key answered the
        # same condition properly, with 429 and `credit_balance_exhausted`. So
        # a 5xx here is not reliably a provider fault, and a message that says
        # "nothing is wrong with your settings, try again later" sends an
        # operator away to wait for someone else to fix the one thing only they
        # can fix.
        #
        # The billing check leads, because it is the cause an operator can
        # confirm in a minute and act on. The provider fault follows, because it
        # is real and there is nothing to do about it but wait.
        return (
            "Could not start the voice session, and the provider did not say "
            "why. Check your OpenAI credit balance first: an account with no "
            "credits left fails here exactly like this, with no explanation. "
            "Add credits at platform.openai.com under billing. If the balance "
            "is fine, the provider is having trouble and it will clear on its "
            "own."
        )
    if "not supported in realtime" in body or "invalid_model" in body:
        return "That model cannot be used for speech. Voice needs a live model such as gpt-live-1."
    return f"The voice provider refused the session (HTTP {status})."


def probe() -> VoiceProbe:
    """Mint a throwaway session to prove the stored key works, then discard it.

    A minimal offer is used rather than a real one: the question is whether the
    credential and the model are good, and a session nobody connects to is
    dropped by the vendor on its own.

    Returns:
        A :class:`VoiceProbe`.
    """
    from services.agent import settings

    config = settings.get_voice_config()
    model = str(config.get("voice_model") or "gpt-live-1")

    if not settings.voice_key():
        return VoiceProbe(
            ok=False,
            message="No OpenAI key is stored for the voice agent, so there is nothing to test.",
            latency_ms=0,
            model=model,
        )

    started = time.monotonic()
    try:
        # voice_enabled gates the live route, not the test: an operator must be
        # able to prove a key works before switching the feature on.
        mint_session(_PROBE_OFFER, {**config, "voice_enabled": True})
    except VoiceUnavailable as exc:
        return VoiceProbe(
            ok=False,
            message=str(exc),
            latency_ms=int((time.monotonic() - started) * 1000),
            model=model,
        )

    return VoiceProbe(
        ok=True,
        message=f"{model} answered and the key works.",
        latency_ms=int((time.monotonic() - started) * 1000),
        model=model,
    )


#: A complete, parseable WebRTC offer used only to prove a credential.
#:
#: It has to be a real offer rather than a token string: the vendor validates
#: the key before the offer but the **model after it**, so a malformed offer
#: proves only that the key exists and would report a model that cannot speak
#: as working. Nothing ever connects to the session this mints, so the ICE
#: credentials and certificate fingerprints below are inert placeholders and
#: carry no host address.
_PROBE_OFFER = (
    "v=0\r\n"
    "o=- 0 0 IN IP4 0.0.0.0\r\n"
    "s=-\r\n"
    "t=0 0\r\n"
    "a=group:BUNDLE 0 1\r\n"
    "a=msid-semantic:WMS *\r\n"
    "m=audio 9 UDP/TLS/RTP/SAVPF 96 9 0 8\r\n"
    "c=IN IP4 0.0.0.0\r\n"
    "a=sendrecv\r\n"
    "a=extmap:1 urn:ietf:params:rtp-hdrext:sdes:mid\r\n"
    "a=extmap:2 urn:ietf:params:rtp-hdrext:ssrc-audio-level\r\n"
    "a=mid:0\r\n"
    "a=msid:probe probe\r\n"
    "a=rtcp:9 IN IP4 0.0.0.0\r\n"
    "a=rtcp-mux\r\n"
    "a=ssrc:350726838 cname:probe\r\n"
    "a=rtpmap:96 opus/48000/2\r\n"
    "a=rtpmap:9 G722/8000\r\n"
    "a=rtpmap:0 PCMU/8000\r\n"
    "a=rtpmap:8 PCMA/8000\r\n"
    "a=end-of-candidates\r\n"
    "a=ice-ufrag:probe\r\n"
    "a=ice-pwd:probeprobeprobeprobeprobe\r\n"
    "a=fingerprint:sha-256 10:B5:AC:80:AB:03:AC:BE:31:AA:73:30:BA:AB:62:80:07:18:1C:A8:D2:0E:17:B0:84:16:DC:E0:C9:AA:D3:50\r\n"
    "a=fingerprint:sha-384 14:CF:CF:50:3E:D6:33:43:82:88:ED:20:74:04:F6:80:B4:F7:6F:37:36:53:97:89:AE:30:1E:6C:CE:25:E0:54:45:B0:89:5A:F4:FB:0B:CC:6B:FB:24:8C:F8:A2:30:23\r\n"
    "a=fingerprint:sha-512 C6:8C:33:83:7C:C0:F5:71:48:6C:03:5F:64:07:C3:6B:BB:60:31:C6:F4:7B:0B:F9:23:6D:93:85:45:4C:32:0D:C2:CC:CD:8D:9A:3B:4E:AE:F3:82:B5:F0:4D:73:19:F5:BE:09:8D:12:16:06:16:ED:D4:ED:40:62:06:F0:F0:23\r\n"
    "a=setup:actpass\r\n"
    "m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n"
    "c=IN IP4 0.0.0.0\r\n"
    "a=mid:1\r\n"
    "a=sctp-port:5000\r\n"
    "a=max-message-size:65536\r\n"
    "a=end-of-candidates\r\n"
    "a=ice-ufrag:probe\r\n"
    "a=ice-pwd:probeprobeprobeprobeprobe\r\n"
    "a=fingerprint:sha-256 10:B5:AC:80:AB:03:AC:BE:31:AA:73:30:BA:AB:62:80:07:18:1C:A8:D2:0E:17:B0:84:16:DC:E0:C9:AA:D3:50\r\n"
    "a=fingerprint:sha-384 14:CF:CF:50:3E:D6:33:43:82:88:ED:20:74:04:F6:80:B4:F7:6F:37:36:53:97:89:AE:30:1E:6C:CE:25:E0:54:45:B0:89:5A:F4:FB:0B:CC:6B:FB:24:8C:F8:A2:30:23\r\n"
    "a=fingerprint:sha-512 C6:8C:33:83:7C:C0:F5:71:48:6C:03:5F:64:07:C3:6B:BB:60:31:C6:F4:7B:0B:F9:23:6D:93:85:45:4C:32:0D:C2:CC:CD:8D:9A:3B:4E:AE:F3:82:B5:F0:4D:73:19:F5:BE:09:8D:12:16:06:16:ED:D4:ED:40:62:06:F0:F0:23\r\n"
    "a=setup:actpass\r\n"
)


def speakable(text: Any) -> str:
    """Trim an answer to something worth hearing.

    The screen already has the full answer, so this is not a summary: it is a
    length guard on the one path that reaches the data channel, so a model that
    ignores its brevity instruction cannot make the trader sit through a page of
    prose.

    Markdown is stripped rather than spoken, because a speech model reading
    asterisks and pipe characters aloud is the most obvious way this feature
    sounds broken.

    Args:
        text: The agent's answer.

    Returns:
        Plain speakable text, no longer than :data:`SPEAKABLE_CHAR_BUDGET`,
        cut at a sentence boundary where one is available.
    """
    import re

    raw = str(text or "").strip()
    if not raw:
        return ""

    # Fenced code and tables are unspeakable; drop them rather than read them.
    raw = re.sub(r"```.*?```", " ", raw, flags=re.DOTALL)
    raw = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("|"))
    raw = re.sub(r"[*_`#>]+", " ", raw)
    raw = re.sub(r"^\s*[-+]\s+", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", raw)
    raw = re.sub(r"\s+", " ", raw).strip()

    if len(raw) <= SPEAKABLE_CHAR_BUDGET:
        return raw

    clipped = raw[:SPEAKABLE_CHAR_BUDGET]
    cut = max(clipped.rfind(". "), clipped.rfind("? "), clipped.rfind("! "))
    if cut > SPEAKABLE_CHAR_BUDGET // 2:
        return clipped[: cut + 1].strip()
    # The ellipsis is spoken, so it comes out of the budget rather than being
    # added on top of it: appending it to a full-budget slice returned 483
    # characters against a documented cap of 480, and a guard that overruns its
    # own limit is not a guard.
    clipped = raw[: SPEAKABLE_CHAR_BUDGET - 3]
    return clipped.rsplit(" ", 1)[0].strip() + "..."


# ---------------------------------------------------------------------------
# Spoken order approval
#
# The matcher in `services.agent.safety.voice_confirm` decides whether an
# utterance is the phrase. This part decides whether it may be asked at all:
# that trading is reachable on the voice surface, that a run really is waiting,
# and that it has not been waiting too long.
#
# The decision is made here rather than in the browser so a defect in the page,
# or a page that has been altered, cannot turn a sentence into an approval. It
# is not the control that stands between a sentence and a broker - that is the
# risk guard inside the tool body, which runs after any approval and reads no
# prompt. This narrows a usability hazard: a word said in a room with other
# people in it.
# ---------------------------------------------------------------------------

#: When each paused run began waiting, keyed by run id.
#:
#: Written from agno's real OS thread when a run pauses, and read from a request
#: greenlet. **Deliberately unlocked.** A lock here would be one of the two
#: crossings `CLAUDE.md` forbids, and none is needed: a single dict key
#: assignment and a single lookup are each atomic under CPython, and the worst a
#: race can do is read a pause one instant before it is recorded, which reports
#: a closed window and falls back to the card.
_PAUSED_AT: dict[str, float] = {}

#: How many paused runs to remember. A pause that is never answered is dropped
#: rather than accumulated: the registry is a window, not a record, and
#: `ag_audit` is where a pause is actually accounted for.
_PAUSE_REGISTRY_LIMIT = 64


def note_pause(run_id: Any) -> None:
    """Record that a run has begun waiting for approval.

    Args:
        run_id: The run that paused. Falsy values are ignored, because a pause
            that cannot be named cannot be approved by voice either.
    """
    key = str(run_id or "").strip()
    if not key:
        return
    if len(_PAUSED_AT) >= _PAUSE_REGISTRY_LIMIT:
        # Drop the oldest rather than grow without bound. Insertion order is
        # guaranteed, so the first key is the least recent pause.
        for stale in list(_PAUSED_AT)[: len(_PAUSED_AT) - _PAUSE_REGISTRY_LIMIT + 1]:
            _PAUSED_AT.pop(stale, None)
    _PAUSED_AT[key] = time.monotonic()


def forget_pause(run_id: Any) -> None:
    """Close a run's approval window.

    Called once a run has been approved, rejected or abandoned, so the same
    utterance cannot approve it twice.

    Args:
        run_id: The run to forget.
    """
    _PAUSED_AT.pop(str(run_id or "").strip(), None)


@dataclass(frozen=True)
class ApprovalVerdict:
    """The answer to one spoken approval attempt.

    Attributes:
        approved: Whether the run may now be confirmed.
        reason: Why not, in words an operator can act on. Empty when approved.
    """

    approved: bool
    reason: str = ""


def judge_approval(
    run_id: Any,
    transcript: Any,
    config: dict[str, Any] | None = None,
) -> ApprovalVerdict:
    """Decide whether one spoken utterance approves one paused run.

    Four things must hold, and they fail for different reasons on purpose: an
    operator who says the phrase into a closed window should be told the window
    closed, not that they said the wrong word.

    Args:
        run_id: The paused run the utterance is aimed at.
        transcript: What the speech model heard.
        config: The voice configuration. Read fresh when not supplied.

    Returns:
        An :class:`ApprovalVerdict`. Approving consumes the window, so a second
        attempt on the same run is refused.
    """
    from services.agent import settings
    from services.agent.safety import voice_confirm

    config = config or settings.get_voice_config()
    if not config.get("trading_effective"):
        return ApprovalVerdict(False, "Placing orders by voice is switched off.")

    key = str(run_id or "").strip()
    opened_at = _PAUSED_AT.get(key)
    window = int(config.get("voice_confirm_window_seconds") or 0)
    if not voice_confirm.window_is_open(opened_at, time.monotonic(), window):
        return ApprovalVerdict(False, "The time to approve that by voice has passed.")

    if not voice_confirm.is_spoken_confirmation(transcript):
        # Not an error and not logged as one: a trader talking near a pending
        # order says plenty of things that are not an answer to it.
        return ApprovalVerdict(False, "That was not a confirmation.")

    forget_pause(key)
    logger.info("Voice approval accepted for run %s", key)
    return ApprovalVerdict(True)
