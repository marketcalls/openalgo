# Intraday Boost: what to do on a trading day

Written 18-Sep-2026, after two recorded sessions and a morning lost to a
sleeping machine. It exists so a trading day needs nothing remembered.

## Your part

**Start OpenAlgo before 09:15.** That is the whole of it.

```sh
uv run app.py
```

Everything else is scheduled. If the machine was asleep or the app was down for
part of the session, the missed minutes are reconstructed from the broker's
candles on the next start, and a stalled recorder or token is restarted by a
watchdog without anyone noticing.

## The one thing to read

`log/tf_boost_daily/<date>.log` — four lines by 09:36:

```
[09:15:xx] app started -- recording from 09:15
[09:25:00] OK morning check -- N beats, N symbols recorded, token present
[09:35:xx] latency check starting
           ... WITHIN the 40s budget
```

`OK` on every line means it is working. `ATTENTION` names what broke. If the
09:25 line is missing entirely, the app was not running.

## What runs, and when

| Time | What |
| --- | --- |
| 09:15-15:30 | Records the ranked lists every 30 seconds |
| 09:25 | Morning check: beats, symbols, token life |
| 09:35 | Latency check: is a badge on screen inside 40 seconds |
| 15:45 | Behaviour study (two entry windows), verify sheet, option audit |
| every 60s | Watchdog: restarts a stalled recorder, and the token keep-alive |

Outputs land in `log/`: `tf_boost_behaviour_<date>_<window>.md`,
`tf_boost_verify_<date>.txt`, `tf_boost_option_audit_<date>.txt`.

## Reading the badge

A `RUN` badge means the move is going one way and not giving much back. The
number beside it is **how long it has been running** — a four-minute run and a
hundred-minute one are different trades, and the badge dims past 45 minutes.

Hover it for the whole story: rank path, how far it has moved since it turned,
how much it gave back, and the stock's actual move on the day. Travel from the
turn is not the day's move; both are shown so they cannot be confused.

`RUN` down is shown and is **not yet proven**. It beat the up side on 18-Sep
(81% against 76%) and lost on 17-Sep, which was a strongly rising day. Two days
decide nothing.

Other badges — `◆T5`, `JUMP`, `→T10` — are about **rank**, not price, so they
appear on falling stocks too. A badge is an observation, never a
recommendation.

## By hand, if you want it

```sh
uv run python scripts/tf_boost_health.py               # is it recording right now
uv run python scripts/tf_boost_latency_check.py        # measure the delay yourself
uv run python scripts/tf_boost_verify.py               # today's badges and what followed
uv run python scripts/tf_boost_option_audit.py         # the option on each badge's own side
uv run python scripts/tf_boost_gate_compare.py A B C   # the open question about the rating gate
```

Never pipe these through `2>/dev/null`: a study that stored nothing looks
exactly like one that worked.

## Open questions, for a week's data and not a day's

1. **Down runs.** Worth taking, or noise? Split rising days from falling ones
   before answering; averaging them is how this was got wrong once already.
2. **The rating gate.** A badge needs top-20 or a ten-place climb *since first
   seen*, which hides a stock that sank and recovered — ADANIGREEN ran +1.6% to
   +4.6% on 18-Sep and badged 85 minutes in. `tf_boost_gate_compare.py` measures
   the candidate; move the gate only if it wins on both kinds of day.
3. **Option bracket.** A +25% target with a 25% stop was the only profitable one
   on both recorded days. The tighter and wider brackets lost on both.
