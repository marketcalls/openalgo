# Indicator alert policies

Descriptor alerts retain evaluation of newly appended observations when no
frequency is declared. Explicit frequency choices use
the existing native event, without introducing notification delivery or changing
the trader-alert controller's saved schema.

## Frequency contract

The optional `frequency` selects `everyUpdate`, `oncePerBar`, `onBarClose` or `once`.
Every update means each observed live calculation, after chart batching; it does
not promise an event for a tick that was superseded before calculation. Once per
bar waits for the first matching live calculation, including a condition that
was false when the bar opened. Close evaluates once when confirmation becomes
known. Once delivers the first matching live result during that instance's
lifetime. Removing and recreating the study creates a new lifetime.

Keep checkpoints per alert identity and source generation. The once-only delivered
latch survives source, history and replay generations for the instance lifetime.
Source replacement and history reset seed bar checkpoints without delivering loaded signals. Historical
calculation, replay, settings changes, repaint and asynchronous data recomputation
cannot consume a once-only alert or repeat an already observed live revision.
Historical replay restoration also seeds checkpoints before live updates resume.

## Confirmation and context

Reuse the native calculation context's confirmation rules: fixed and calendar
intervals, explicit provider overrides, count-driven observations and replay.
Appending a newer observation closes the previous observation, including count
bars, matching the existing calculation context's treatment of earlier bars.
Do not apply the new tail's provider override to earlier observations. Coalesced
appends evaluate every newly completed observation after the close checkpoint.
Closing an observation does not require its price to change. Clock closure waits
for an eligible live source execution; settings, repaint and asynchronous refresh
alone do not deliver a close alert. There is no independent polling timer.

Close predicates receive only the bar and output prefixes through the evaluated
index, preventing direct reads of a later forming observation. This limits callback
visibility; it cannot remove future information embedded by a noncausal calculation.
Study authors remain responsible for causal alert inputs. A predicate
that was false at close is still judged and is not retried after later price
updates. A same-time provider confirmation can close the current observation.

Reserve each evaluation and fence the pass before and after predicates, message
builders and subscribers. All can synchronously update data, change settings or
remove the study. Snapshot the pass inputs and abandon stale continuation. Commit
delivery state before emitting. The guarantee is at-most-once native event
dispatch, not acknowledged notification delivery by every subscriber.

A false close condition is judged permanently. Predicate or message errors leave
delivery and once-only latches unspent, but the same failed revision is not
automatically retried. A later eligible live revision may retry that close while
its observation remains available. Evaluate independent sibling specs, retaining
their successful checkpoints, then report the first error through the existing
calculation error status. Repeated reads cannot duplicate delivered siblings.

Capture the calculation's original execution context before source checkpoints
advance. Alert checkpoints are separate from calculation caching. Compare history
revision as well as final provenance: a correction followed by a coalesced live
append still seeds historical state. The omitted-frequency path retains its
tail-only gate; explicit policies use the stronger native provenance. Either way a
calculation that appended several bars after an unchanged prefix (a batched burst,
or one source bar completing several transformed elements) judges each new bar in
order on its own prefix, as separate appends would. A transformed chart's forming
element dated forward at its index by a newer source bar (Kagi, range bars) is the
same bar revised, not a correction: the watermarks, the per-bar checkpoint and the
close checkpoint follow it to its new time. A study on the bars under a transform keeps
its watermarks and checkpoints in the times of those bars, which never move: the
elements one underlying bar completed read that bar and are judged as one observation,
at the first of them, and the observation closes when that bar closes.

## Verification sequence

1. Keep all omitted-frequency custom-host and native cases unchanged.
2. Prove false-at-open then true-within-bar behavior, repeated same-time updates,
   coalesced updates, and once-only behavior across multiple bars.
3. Exercise previous-bar close, explicit same-time confirmation, count bars,
   sparse sessions and calendar intervals with independent clocks.
4. Verify source changes, corrections, prepend, settings, asynchronous refresh,
   replay entry/exit and repeated reads never deliver historical signals.
5. Cover event-handler removal and reentry, error recovery and independent
   instances. Run compiled descriptors through the unchanged public adapter and
   demonstrate the event stream in a runnable browser example.
