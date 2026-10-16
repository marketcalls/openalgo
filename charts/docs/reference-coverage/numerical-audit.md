# Numerical audit

The audit inventories all 105 shipped indicator descriptors and compares
equivalent calculations with both companion language engines. Inventory and
successful execution are not numerical conformance. The complete audit remains
open, including documented differences in seeds and missing-value behavior.

The expanded ADX audit found a Python-only defect after 0.7.0 publication:
selected movement can overflow from finite prices and enter recursive state
without normalization. A five-bar fixture has four differing cells; native and
npm recover while Python remains unavailable. A corrective patch is being
prepared in an isolated checkout. The earlier recorded corpus remains useful
evidence for its tested inputs, but it does not establish agreement on this new
boundary.

## Directional movement seed

Positive and negative movement now seed from the same first real change window
as true range. A synthetic rising series with a unit movement and a two-unit
range therefore reports positive direction 50 as soon as it is available.
Including a fabricated zero movement at the first bar previously biased this
reading downward.

For high/low/close rows `(10,8,9)`, `(12,9,11)`, `(11,7,8)`, `(13,9,12)` and
`(12,10,11)`, with both lengths set to 2, independently derived strength is
`[null,null,null,25,37.5]`. The final positive and negative readings are 24 and 8.
Both companion engines already produce these ordinary-case results.

That seed correction preserved first-available indices and the then-existing
chart behavior on zero range and absent observations. The later seeded recurrence
audit exposed a separate gap: unavailable high/low changes were counted as zero,
while an unavailable true-range seed or update could leave ratios frozen forever.
Correcting the recurrence alone let true range resume and exposed those decayed
movement numerators. The observation-policy correction treats unavailable
movements as absent, retains each smoother's state and requires current
directional readings before advancing strength.

Zero smoothed true range also leaves both directional ratios and strength absent,
matching the companion contract. The previous native display carry could repeat
a stale ratio and feed its DX into the strength smoother despite an undefined
current division. A flat bar's zero movement remains a real finite observation;
an unavailable high/low change does not become a zero movement.

The observation correction passes 267 focused tests. Fifteen freshly compiled
cases compare 396 cells exactly between native and npm. Fourteen cases and
381 cells also agree with Python; the remaining finite-difference overflow
fixture exposes the four-cell Python defect described above. A separate
independent seven-case corpus matches 114 cells across all three implementations,
covering flat ranges and resumed strength. All 45 affected numerical browser
cases pass across three engines, including gaps, zero ranges and forming-bar
rewrites; actual screenshots were inspected.

Verification includes 129 focused unit tests, same-time chart updates and prefix
execution. A built-package browser regression first reproduced the old wrong
values, then passed exact readings and rendered-line pixels in all three browser
engines. Screenshots were inspected. Typechecking, scoped lint, build and bundle
budgets passed. That development build measured 36.00 kB Brotli for the indicator
tier and 289.25 kB for all tiers together.

## Hull window lengths

The standalone HMA now shares the integer-window kernel used by Hull Suite's Hma
mode and both companion engines. The fast window is `max(1,floor(length/2))` and
the smoothing window is `max(1,round(sqrt(length)))`. Length 1 returns its source.
The former fractional half window changed the slope response at odd lengths;
flooring the outer square root could also emit a value before the agreed warmup.

Independent straight-line lag fixtures cover lengths 1, 2, 9, 13, 16 and 25.
At length 9 a ramp is followed without lag once warm; at length 13 the lag is
one third of a bar and the first reading is at zero-based index 15. Flat values,
source holes, recovery and prefix execution are checked separately. These are
formula comparisons; unchanged summation orders can still differ in last bits
from the companion engines and remain part of the wider audit.

The Hull batch passes 173 focused unit tests, typechecking and scoped lint.
Built-package Hull and directional-value regressions pass in all three browser
engines, with screenshots inspected. Fifteen matching compiled programs produce
identical bits between the companion engines. The six Hull fixtures now match
the chart formulas and availability within the stated `1e-12` comparison;
directional zero-range and absent-data differences remain open. The current
build measures 35.90 kB Brotli for indicators and 289.15 kB for all tiers, within
their budgets.

The companion audit additionally reproduced and corrected changing-length,
volume-anchor, overflow and partial-output disagreements. Both packages are
published at 0.7.0 from source `f9ab00e4`. The chart release remains 2.5.4 and is
pending the remaining native capability work.

## Wider compiled comparisons

The complete descriptor inventory now exercises all 105 descriptors and 266
declared outputs. The 1,148 compiled cases compare 1,287,674 output cells between
the companion engines without differing bits or absence. This includes secondary
lines, bands, displaced outputs, event columns and explicitly identified table
carriers. Calendar fixtures separately check 86,866 table cells. Event tests
distinguish confirmation indices from plotted origin indices, so a backdated
marker cannot conceal premature availability.

The companion release gates also pass all 116 scalar and stateful numerical
signatures: 6,836 cases and 1,504,908 accepted calls. Independent field shocks,
declared defaults, changing lengths, checkpoint restoration and replay are
included. Power, trigonometry, exponential, logarithmic and hypotenuse kernels
have independent rounding evidence. Fresh installed distributions run 363
compiled programs, with 124,977 exact cross-engine cells and 6,756 independently
expected cells. These finite corpora are not a proof of every possible history.

The same installed-program and independent-oracle checks pass using downloaded
public 0.7.0 distributions. All 1,617 package files, 108 wheel modules and 181
source-distribution files match the immutable source or the verified generated
build. Registry integrity and attestation subject, source and workflow claims
match; cryptographic signatures and transparency inclusion were not verified.

After the RSI correction, 197 outputs differ in at least one exercised case,
38 agree on the sampled finite inputs and 27 are
constant outputs. Two outputs carry tables, and two event columns that are
absent in broad fixtures have separate finite, independently derived fixtures.
Differences include arithmetic order, gaps and documented algorithm choices;
the count does not mean every difference is a calculation defect. Neither a
relative tolerance nor two identically absent outputs establishes agreement.

A later source refresh after the chronological-window and CPR corrections runs
all 1,148 existing cases against their recorded compiled outputs. It compares
1,286,742 aligned cells: the recorded companion outputs still agree exactly,
while 135 native output columns differ in at least one case. Another 99 columns
agree across varied finite values, 28 have only one distinct finite value and
four have no finite observations in this corpus. These last two categories are
not evidence of numerical equivalence. This refresh does not rerun compilation,
calendar-table oracles or causal marker timing. Remaining differences include
ordinary last-bit arithmetic, missing observations and distinct algorithms.

After seeded recurrence recovery, the same recorded corpus has 109 differing
columns and 125 with exact varied finite observations. Single-value and absent
categories are unchanged. Total differing cells decrease from 126,450 to 105,031;
38 columns improve and none increase in total differences. Availability
differences fall from 75,899 to 51,271, while finite-bit differences rise from
50,551 to 53,760 as recovered output exposes remaining arithmetic differences.
This is another source refresh against recorded engine results, not new
compilation or a universal equivalence claim.

The directional observation correction makes its three columns exact on this
same corpus, leaving 106 differing columns and 128 with exact varied finite
observations. It removes another 5,001 differences, leaving 100,030 differing
cells. Constant/absent classifications are unchanged. The new Python overflow
counterexample is outside these recorded inputs, so agreement of the recorded
engine arrays cannot support a global claim about the published engines.

## Confirmed boundary corrections

Default positive safe-integer scalar `smaSeededEma` and `rma` now seed from the
first complete finite chronological window. Missing or overflowing seed windows
can expire and recover. After seeding, an absent input emits a gap while keeping
the running state. A nonfinite update from a finite input stays committed rather
than freezing or reseeding. Public first-value EMA, explicit compensated options,
resolved study-source propagation and unsupported scalar paths retain their
existing behavior.

The correction passes 420 focused tests, including 27 new cases. Seventeen fresh
compiled fixtures compare 340 cells exactly across native, npm and Python
calculations, covering twelve helper cases, four composed studies and signed
zero. Independent review checks 20,000 generated cases and 161,328 cells against
a separate seed-search oracle, plus 90,000 exact comparisons of preserved routes
against the previous commit. This is finite-corpus evidence, not a universal
equivalence claim for every composed study.

Both new browser regressions failed against the previous bundle. All 45 affected
numerical browser cases then passed across three engines. New checks cover actual
line and marker pixels, gap recovery and forming-bar replacement/removal. Six
representative recurrence screenshots and six directional screenshots were inspected.

Ordinary recurrence costs O(bars + period), with constant working space excluding
output. Repeated overflowing seed windows can cost O(bars * period). At 20,000
bars and period 1,000, measured median times are 0.16 ms for seeded EMA and
0.11 ms for RMA on ordinary finite data, and 10.58 ms and 10.47 ms respectively
with repeated overflowing seed windows. These are observations on the validation
machine, not timing guarantees.

Default positive safe-integer scalar SMA and rolling sums now add each current
window oldest first. Only missing-observation counts are carried between windows.
Nonfinite sums remain unavailable; SMA divides the finite sum once. A singleton
window retains its finite input and normalizes signed zero. This fixes both
expired-overflow poisoning and an ordinary finite cancellation example that
previously created a false MA Cross signal. Explicit SMA options, including an
empty options object, and varying-length windows retain their separate compensated
arithmetic. Unsupported scalar-period behavior is unchanged.

The correction passes 535 focused tests. Nine compiled cases compare 64 cells
exactly against both companion engines. Work is proportional to bars times period,
with constant extra working storage excluding the returned array. At 20,000 bars,
recorded medians are 0.33 ms for SMA length 9 and 17.71 ms for length 1,000; MA Cross
takes 1.68 ms at defaults and 38.49 ms with both lengths at 1,000. These measured
costs do not change performance budgets or constitute timing guarantees.

Default scalar weighted averages, population deviations and absolute deviations
also accumulate terms oldest first and normalize nonfinite final readings. Their
separate compensated option and varying-length paths remain unchanged. The
correction passes 231 focused tests and 147 exact native/npm/Python cells through
nine newly executed compiled programs, including ordinary last-bit differences,
weighted cancellation, overflow, missing observations and recovery.

CPR seeds high and low only at the existing session or calendar boundaries. A
nonfinite extreme invalidates the whole period; later finite observations cannot
erase it. The next complete period recovers normally. The final close remains
the period's close, and existing display flags and formulas are unchanged. The
correction passes 165 focused tests and matches 270 recorded compiled cells in
the independently specified incomplete-period fixture. The compiled composition
uses explicitly matched boundaries, not a general exchange-calendar guarantee.

Balance of Power now omits nonfinite numerators, ranges and ratios while
preserving finite ordinary results and recovery on the following bar.

Money Flow Index rejects nonfinite selected price flows and window totals before
its zero-negative-flow shortcut. Each window is summed oldest first, correcting
ordinary last-bit differences as well as recovery after expired overflow. Missing
volume still defaults to zero; tied finite prices still contribute zero even
when their unused price-volume product overflows. Twenty-two actual compiled
cases and 991 independent expected cells match the native calculation and both
released companion engines exactly. Sixteen dedicated regressions pass.

This retains work proportional to bars times period. On the recorded machine,
50,000 bars take a median 2.99 ms at period 14 and 17.72 ms at period 500, compared
with 2.07 ms and 22.60 ms before the correction. These are observations, not
timing guarantees or relaxed performance budgets.

WaveTrend computes its signal mean from the chronological window. An incremental
sum previously drifted enough to create a false crossing on a simple rising
series. AlphaTrend's private mean and flow sums use the same fresh-window
principle so an expired infinite contribution cannot poison all later values.
This costs work proportional to bars times period. On the recorded machine,
20,000 bars at AlphaTrend period 500 take a median 32.42 ms rather than 3.62 ms;
WaveTrend with signal length 100 takes 8.58 ms rather than 4.81 ms. These are
observations, not new timing guarantees or raised engine performance budgets.

Seasonality excludes nonfinite month returns from the table and its counts.
Aggregate means or deviations that overflow remain blank. Finite return order,
ignored-month behavior and the still-forming month are unchanged. Table tests
scan headers, body and summary for nonfinite display text.

The composition audit also found overflow boundaries in companion TSI, RSI,
Ultimate Oscillator, MFI, CCI and correlation. Their corrections are verified in
both language runtimes, including compiled historical and forming updates.

Native RSI now treats a missing or overflowing change as unavailable, retaining
any already-seeded gain and loss averages. Unseeded legs independently seek a
complete finite suffix and finite mean. Running arithmetic overflow retains its
state and stays unavailable, instead of silently restarting or emitting zero or
100. Ordinary finite arithmetic and the function signature are unchanged.
All five built-in consumer paths and `rsiSeries` inherit the corrected behavior.
Six actual compiled fixtures agree bit-for-bit with both companion engines.
On the recorded machine, an ordinary 20,000-bar run changes from 0.12 to 0.23 ms.
Repeated failed seeds can require fresh period-length sums before recovery.

The built package passes 21 numerical browser cases across three engines,
including ordinary directional and Hull values, RSI recovery, absent Balance
of Power points, WaveTrend crossing markers, AlphaTrend recovery and finite
Seasonality table pixels. Screenshots were inspected.

## Gap recovery in running studies

The classification of the refreshed comparison attributed six further causes to
the chart: a missing observation that removed a running study for the rest of
the history, or a regrouped formula. Each is now corrected at its source, and a
missing input costs only the bars it covers, apart from the Volatility Stop and
OBV cases listed under the remaining distinctions.

- The base `atr` seeds from the first complete window of finite true ranges,
  keeps its average across a missing or overflowing true range and resumes from
  it. A running overflow stays unavailable instead of reseeding. A true range
  reads the previous close, so a missing close costs the ATR the next bar rather
  than its own. Keltner, Chandelier Exit, Chande Kroll Stop, Median, HalfTrend
  and Volatility Stop read it and inherit the correction, and Volatility Stop no
  longer falls back to the unmultiplied true range after a gap.
- `supertrend` leaves a bar with no ATR or no close absent, with its bands,
  direction and last accepted close unchanged. A missing close has a finite ATR
  on its own bar, and its NaN comparison flipped the trend, which the resumed
  ATR would otherwise have carried into every later bar.
- VWAP leaves a bar with a missing price or a nonfinite volume absent and its
  totals untouched; an undefined volume still counts as nothing traded.
- TWAP skips a missing price and divides by the bars it counted.
- OBV and Accumulation/Distribution read a nonfinite volume as nothing traded,
  as the money-flow studies already did. Accumulation/Distribution leaves a bar
  missing its high, low or close, or whose span or term overflows, absent with
  its total unchanged.
- Parabolic SAR steps over a bar missing its high, low or close, seeds from the
  first two complete bars and clamps against the two complete bars before each
  step.
- TEMA adds its three terms left to right, as the specification fixes them.

The minimal ATR, Keltner, VWAP, TWAP and TEMA cases the classification recorded
for these causes now read exactly as their expected values. The Supertrend line,
OBV, A/D and Parabolic SAR cases differ only in cells of a documented contract
difference: the Supertrend seed bar, the carried OBV and A/D total on the bar
whose volume is missing, and the Parabolic SAR clamp. Finite results on complete
data are unchanged: digests of 27 affected configurations over five generated
sessions, recorded from 2.5.4 before the change, match bit for bit, and the
public `atr` equals the 2.5.4 recurrence at periods 1, 2, 3, 14, 50 and 500.
TEMA is the exception by design and moves only in its last digits. Reverting
each correction fails its own regression tests, and four browser regressions
paint the resumed ATR, Supertrend, VWAP, band, Parabolic SAR, OBV and
Accumulation/Distribution readings, a Supertrend that keeps its side across a
missing close, and no bridge across a gap, in all three browser engines.
Screenshots were inspected.

## Cell classification

A classification of the post-directional refresh assigns each of its 106
differing columns (100,030 cells) exactly one class, the highest-priority class
among its verified causes: chart defect (49 columns), contract difference (49),
comparison artifact (7) and companion engine defect (1). Every cell is
attributed to one cause. The recorded companion arrays are 0.7.0; the released
0.7.1 engines reproduce every recorded cell used here.

### Chart defects corrected in this change

- **CCI** (979 cells). The deviation guard read `md > 0 ? ... : 0`, so a window
  holding a missing high, low or close (a NaN mean deviation) or an overflowing
  one printed CCI 0 for `period` bars, and the CCI-based average and Bollinger
  bands smoothed those invented zeros. A non-finite deviation now leaves the bar
  absent. The flat-window zero is the separate, documented K3 below.
- **Stochastic** (1,931 cells). %K is `(100 * (close - lowest)) / span`, the
  arrangement the language fixes in standard library section 20.4, where it
  divided first. A span that overflows is absent instead of dividing a finite
  distance down to 0; an overflowing scaled distance is an infinity that the
  smoothing and plot drop. %D inherits both.
- **Fisher Transform** (1,273 cells). The two recursions reset only when the
  window span was not finite. Because the window extremes skip a missing
  midpoint (K1), the span stayed finite on such a bar and NaN entered both
  recursions for the rest of the history. A missing midpoint now resets and
  skips the bar, which is the descriptor's own documented rule.
- **Relative Volatility Index and Mass Index** (3,507 cells). The RVI's private
  EMA and the Mass Index's run-by-run second EMA restarted from a fresh simple
  mean after any gap, blanking the study for another 14 or 9 bars. The Mass
  Index now runs the SMA-seeded EMA over the whole series, which holds its
  state across a gap (standard library 20.2.2). The RVI's two averages keep the
  reference recursion inside the deviation warmup, where a hole restarts them
  as before (K12), and hold across a hole from the deviation's first reading
  on, which only a missing close can make. The RVI's EMA smoothing option uses
  the SMA-seeded EMA and holds as well.
- **True Strength Index, SMI Ergodic Indicator and SMI Ergodic Oscillator**
  (8,869 cells). The ratio is `(100 * doubleSmoothedChange) / doubleSmoothedSize`
  (standard library 20.4). Above about 1.8e306 the product overflows and the
  bar is absent, as in the language.
- **Trend Strength Index and `correlation`** (3,638 cells). Each window takes
  two passes, oldest first: both means are finished, then cross products and
  squares of the deviations, and the result is
  `(cross / len) / (sqrt(squaresA / len) * sqrt(squaresB / len))` (standard
  library 20.8). The single pass lost about one percent of the reading at a
  price of 1e5 with 0.01 moves and had no reading at 1e9.
- **NVI and PVI** (not a classified cause). A missing close on a bar whose
  volume qualified was compounded into the running product and removed the
  index and its average for the rest of the history. A missing close now holds
  the index, as a zero or missing previous close already did, so both lines
  carry on. The index therefore has no gap for its average to restart after.

The boundary tests in `tests/indicator-numeric-absence.test.ts` use recorded
companion readings or hand derivations, and failed on the previous sources.
Reverting each individual change (the CCI guard, the Stochastic order and span
guard, the Fisher midpoint guard, the RVI hold after the deviation warmup, the
RVI smoothing average, the Mass Index second average, the TSI order, the
two-pass correlation and the NVI and PVI close guard) makes between one and
three of them fail; holding the RVI averages inside the warmup as well makes
the complete-data check and the Length 30 parity case fail. Five
built-package browser regressions (CCI, Fisher, RVI with Mass Index, Trend
Strength at 1e9, and NVI across a missing close) failed on a build of
the previous sources and pass on the corrected build in Chromium, Firefox and
WebKit; the screenshots were inspected.

Ordinary data was compared against the previous sources on 22 gapless series
(a sine wave at 100 and 1e5, random walks at levels 1, 5, 100, 25,000 and
100,000): all 105 descriptors at their defaults and the affected ones at varied
settings, 4,060,000 cells in 311 columns. CCI, Fisher Transform, Mass Index and
every unrelated descriptor are bit-for-bit unchanged. Stochastic and the TSI
family move only in the last bits (at most 5.4e-16 relative for %K and %D, and
2.9e-14 on the 0 to 100 scale of the signal lines) with identical availability.
Trend Strength is within 6.7e-16 of an exact rational correlation on every
cell; the former single pass was off by up to 0.084 on 2-bar windows and missed
one reading.

The RVI, NVI and PVI are bit-for-bit unchanged on complete data at every
setting tried. Their unit tests compare the RVI with the 2.5.4 formula at
deviation Lengths 2, 10, 14, 16, 17, 30 and 100, with and without the EMA
smoothing, on six series chosen so that the longer lengths meet a seed inside
the warmup followed by a hole, the case where holding would move the reading;
NVI and PVI are compared at four average lengths on three series. A sweep
against the 2.5.4 sources themselves covered deviation Lengths 1 to 120, 150
and 200 with all eight smoothing options, NVI and PVI at four average lengths
and PVO at five settings, over fourteen complete series including stretches of
zero volume: 33,555,900 cells, none different. Every built-in at its defaults
on eight further complete series (1,170,400 cells) differs from 2.5.4 only in
Stochastic and the TSI family, in the last bits, and in Trend Strength, by the
former single pass's error. Availability is identical on those series, none of
which holds a window of identical closes, and for Trend Strength that is as far
as the statement goes. On such a window the two-pass form gives
no reading when the deviations are all exactly zero, which needs an exact mean
(fourteen bars of 5 or of 0.1), and reads exactly 0 when the mean is inexact
(three bars of 0.1, fourteen of 2.01), as the language does. The single pass
printed nothing or its own residue on these windows, so availability moves in
both directions: three bars of 0.1 went from none to 0 and fourteen of 0.1 from
-1.2e-8 to none, while fourteen of 2.01 went from 2.8e-8 to 0. On four simulated
5,000-bar tick series (at 2, 8, 350.15 and 24,000, the first three with
frequent unchanged closes) at Lengths 3, 14 and 30, up to 1,274 cells per series
and Length went from none to 0 and up to 658 from a reading to none. Every one
of them was a window of identical closes, and every new reading was 0.
Circuit-locked and illiquid instruments produce these windows.

These corrections move the indicator tier from 36.27 to 36.31 kB Brotli
(36,310 bytes), the widget terminal from 267.55 to 267.59 kB (267,594 bytes)
and all tiers from 310.09 to 310.13 kB (310,127 bytes). Their budgets are now
36.31, 267.60 and 310.13 kB, the smallest two-decimal values that pass.

### Contract differences

These thirteen are documented choices, not defects, and this change does not
alter them. The website indicators page carries the same rules for users under
Numerical contract. For K1 to K11, cell counts are each cause's attributed
cells in the classified corpus (31,926 in all); a column can carry more than
one cause. K12 and K13 came out of correcting D11 and are measured on the
fixtures named in each entry.

**K1. Extremes skip missing observations inside the window** (6,704 cells).
- Chart: `highest`, `lowest`, `highestBars` and `lowestBars` without options
  ignore NaN (it loses every comparison), so a window holding a missing bar, or
  reaching into a chained source's warmup, reports the extreme of the bars that
  are present.
- Language: every windowed function is absent while any bar of its window is
  absent, and warmups compose (standard library sections 1 and 2.4, language
  section 6.7).
- Affected: Ichimoku (661), Stochastic (176), Williams VIX Fix (1,453),
  Donchian (286), Chande Kroll Stop (68), Chandelier Exit (164), Aroon (124),
  Aroon Oscillator (184), Fisher Transform (1,292), Bollinger BandWidth
  expansion and contraction (1,102), Chop Zone (114), SMI (888), Ulcer Index
  (56), Stochastic RSI (52) and Williams %R (84). The same descriptors run
  with the propagate option are exact.
- Rely on: channel, range and extreme-age studies keep printing across a
  missing bar; pass `{ missing: 'propagate' }` to these helpers in your own
  descriptor when a window with a gap must have no reading.

**K2. Missing volume, and in flow studies a missing price, counts as no trade**
(6,200 cells).
- Chart: an undefined volume is zero traded. The money-flow studies also read a
  non-finite flow term as 0, so running totals print their unchanged value and
  averages over them advance on that bar.
- Language: volume is absent, not zero (standard library 3.1); an absent bar
  gives an absent reading and leaves totals and averages unchanged (20.6 and
  20.2.2).
- Affected: VWAP (14), MFI (29), Volume (46), OBV (128), A/D (12), Chaikin Money
  Flow (84), Chaikin Oscillator (1,744), Elder Force Index (942), Net Volume
  (6), VWMA (84), PVT (12), PVO (2,890) and AlphaTrend (209). Treating missing
  volume and price as absent makes Volume, MFI, VWMA, CMF, EFI, PVO and the
  Chaikin Oscillator exact.
- Rely on: a bar with no volume is a bar that traded nothing; totals hold and
  averages still advance where the language would print a gap.

**K3. CCI reads 0 on a window with no deviation** (1,915 cells).
- Chart: a flat window (mean deviation exactly 0) prints CCI 0, and the
  CCI-based average and bands follow.
- Language: dividing by a zero deviation has no value, so `cci` is absent
  (standard library 2.4, language 6.3).
- Affected: CCI (cci 493, average and both bands 474 each).
- Rely on: CCI prints 0 when every typical price in its window is equal; a
  window with a missing bar or an overflowing deviation has no reading.

**K4. First reading one bar earlier** (42 cells).
- Chart: Supertrend prints the raw band on the ATR seed bar (`atrLength - 1`);
  PVT prints 0 on bar 0; Choppiness sums the plain true range, whose bar 0 is
  high minus low, so it prints from bar `length - 1`.
- Language: `supertrend` is absent on the seed bar and starts at `atrLen`,
  `pvt` starts at bar 1, and `chop` uses the gap-aware true range and starts at
  bar `len` (standard library sections 4, 6 and 7; 20.3, 20.5 and 20.6).
- Affected: Supertrend (22), Choppiness Index (9) and PVT (11).
- Rely on: these three print one bar before the language equivalent, which
  withholds that bar.

**K5. Host exponential and logarithms are not correctly rounded** (6,078
cells).
- Chart: ALMA, Choppiness and Fisher use `Math.exp`, `Math.log10` and
  `Math.log`.
- Language: the 0.7 engines use correctly rounded portable recipes (standard
  library 20.10.2); the specification exempts these functions from conformance
  (20.11, gap 1).
- Affected: ALMA (4,616), Fisher Transform (1,068) and Choppiness Index (394).
  Substituting the engine functions makes ALMA exact and removes the Fisher and
  Choppiness bit differences.
- Rely on: these three can differ from the language, and between JavaScript
  engines, in the last bit.

**K6. Percentage units and scaling constants at a different step** (5,013
cells).
- Chart: Historical Volatility is a percentage formed as
  `(100 * stdev) * sqrt(365 / per)`; Ease of Movement applies its divisor
  (10000) inside each bar's term before averaging.
- Language: `hv` is a ratio (20.5), so a comparison multiplies `100 * hv(...)`
  outside the annualisation; `eom` has no scaling constant (20.11, gap 3), so a
  comparison multiplies the mean.
- Affected: Historical Volatility (1,700) and Ease of Movement (3,313).
  Applying the factor at the reference step makes both exact. Bollinger
  BandWidth also reads in percent; compared with the language ratio times 100,
  its reading has no differing cell in the classified corpus.
- Rely on: Historical Volatility reads in percent and Ease of Movement is
  scaled inside each bar; a converted language reading can differ in the last
  bits.

**K7. Aroon Oscillator scales the age difference once** (2,117 cells).
- Chart: `(100 * (upAge - downAge)) / length`, one rounding.
- Language: there is no oscillator call; composing it subtracts two separately
  rounded Aroon percentages (20.3).
- Affected: Aroon Oscillator (2,117).
- Rely on: the oscillator can differ in the last bits from Aroon Up minus Aroon
  Down.

**K8. Parabolic SAR clamp and reversal conventions** (1,570 cells).
- Chart: the stop is clamped to the previous two bars' range, a reversal
  places the stop at the larger of the extreme and this bar's high (mirrored
  for a short), and a tie on the seed pair starts long.
- Language: `psar` is the unclamped recurrence, a reversal stop is the extreme
  reached, and the seed is long only on a strictly higher close (20.3, which
  names the clamp as a different function).
- Affected: Parabolic SAR (1,570). The specification recipe with only the clamp
  added accounts for 1,565 of these; the reversal and tie conventions for the
  rest.
- Rely on: the chart's stop stays outside the previous two bars' range and
  includes the reversal bar, so it differs from the language `psar` on most
  bars of a fast trend.

**K9. Overflow: IEEE infinities against per-operation absence** (1,240 cells).
- Chart: native arithmetic keeps an overflowing intermediate as an infinity,
  which can reach a finite limit (a zero weight, a 90 degree angle, a sign) or
  be skipped.
- Language: every non-finite intermediate is absent at once and a condition on
  an absent value takes the false branch (compiled program 3.1, language 6.3
  and 6.6).
- Affected: Connors RSI (102), Chop Zone (262), Net Volume (3), Klinger
  Oscillator (524), McGinley Dynamic (262), Volatility Stop (2) and AlphaTrend
  (85). Modelling per-operation absence makes McGinley, Chop Zone, Klinger and
  Net Volume exact; the Connors RSI cells were traced by inspection.
- Rely on: near the largest double (about 1.8e308) readings at and after an
  overflowing bar can differ from the language or be absent; ordinary prices
  never reach it.

**K10. Signed zero** (143 cells).
- Chart: the Chop Zone angle and Net Volume can return -0.
- Language: negative zero is normalised to positive zero on every result
  (compiled program 3.1).
- Affected: Chop Zone (60) and Net Volume (83).
- Rely on: a negative zero plots and prints as 0; compare with `=== 0`, not
  `Object.is`.

**K11. Klinger reads a NaN volume as a missing bar** (904 cells).
- Chart: a NaN volume passes through `volume ?? 0`, so the Klinger averages
  skip that bar, while an undefined volume is zero.
- Language: absent volume is absent (3.1); the compared composition encodes the
  chart's documented zero rule with `orElse(volume, 0)`, so this is not a
  departure from the specification.
- Affected: Klinger Oscillator (kvo 458, signal 446). Reading NaN volume as
  zero makes these cells exact.
- Rely on: pass missing volume as `undefined`; Klinger then reads it as zero,
  like every other volume study.

**K12. The RVI averages restart inside the deviation warmup** (measured on
fixtures).
- Chart: the Relative Volatility Index's two 14-bar averages follow the
  reference recursion,
  `sum := na(sum[1]) ? sma(src, 14) : alpha * src + (1 - alpha) * sum[1]`.
  Until the standard deviation's first reading, the upper average's source is
  absent on every bar that rose and the lower average's on every bar that did
  not, and each absent bar restarts the average, which seeds again on the next
  fourteen present bars. From the deviation's first reading on, a hole can
  only come from a missing close, and the averages hold across it.
- Language: there is no call for this study; composed with `ema`, each average
  seeds on its first fourteen present inputs and holds across every later
  absent one, the warmup's included (20.2.2).
- Affected: the RVI at a deviation Length above 16 on a series whose warmup
  holds a fourteen-bar one-way run followed by a bar the other way; the default
  Length 10 never. Against the 0.7.1 engine on the 400-bar test wave the first
  reading is bar 42 in the chart and 38 in the language at Length 30, 52 and 39
  at Length 40, and 112 and 99 at Length 100, and the later readings differ by
  a shrinking amount (4 availability and 241 value cells at Length 30); Lengths
  2 to 25 agree bit for bit there. On runs of exactly fourteen bars the first
  reading is bar 29 against 28 at Length 17.
- Rely on: on complete data the RVI reads exactly as it always has, at every
  length; at a long deviation Length the language's first reading can come
  earlier, and its later readings differ from the chart's until the difference
  decays.

**K13. The PVO signal restarts after a stretch with no reading** (measured on
fixtures).
- Chart: after its warmup PVO has no reading only where the slow volume
  average is exactly 0. The signal average then starts again on the next full
  window of readings, so after PVO prints again the signal and histogram wait
  `signalLength - 1` bars for a new seed.
- Language: there is no call for this study; composed with `ema`, the signal
  holds across the absent readings and resumes on the next one (20.2.2).
- Affected: PVO with the SMA oscillator and the EMA signal, after a stretch of
  zero or missing volume at least one slow window long. With the default EMA
  oscillator the slow average stays above 0 once it has seeded on any volume.
  Against the 0.7.1 engine on a 300-bar wave with 40 bars of zero volume the
  chart's signal and histogram are absent on 8 bars where the language prints,
  and 152 later values differ; with the EMA oscillator nothing differs.
- Rely on: a stretch with no traded volume costs the PVO signal one signal
  window after PVO returns; complete data without such a stretch reads as it
  always has.

### NaN volume

An undefined volume is zero traded in every built-in (K2), and that is the rule
to rely on. A NaN volume is treated two different ways, so no single rule can be
written down for it. Setting one bar's volume to NaN and, separately, to
`undefined` on a 300-bar series, for every descriptor at its defaults and with
each VWMA smoothing option, gives:

| Treatment of a NaN volume | Built-ins |
| --- | --- |
| Zero, identical to an undefined volume | Chaikin Money Flow, Chaikin Oscillator, Ease of Movement, Elder Force Index, Net Volume, VWMA, the VWMA lines of MA Ribbon, NVI, PVI, PVT, PVO, OBV with its smoothing and bands, A/D |
| A missing bar: that bar and any window or average holding it are absent, then the study recovers | Volume and its average, MFI, Klinger Oscillator (K11), AlphaTrend, the VWMA smoothing option of CCI and of the RVI, VWAP and its bands (that bar has no reading and the running totals leave it out) |

VWAP, OBV and A/D follow the gap recovery change (D2 and D4). In 2.5.4 a NaN
volume blanked VWAP until its next anchor restart, which on the continuous
anchor was never, and removed OBV and A/D for the rest of the history on any
bar where it entered the total. Until the chart settles on one treatment, hosts
should send a bar without volume as `undefined`.

### Still open

The other classified chart defects (ATR after a missing observation, VWAP and
TWAP running totals, OBV and A/D with a NaN volume, the TEMA grouping and
Parabolic SAR after a missing high or low) are corrected by the gap recovery
change, not here. Two of those studies still do not hold their state across
every gap. Volatility Stop restarts its stop at the source on a bar with no true
range, as its reference definition does, and after a missing source, so its
level and sometimes its side differ from complete data for some bars. OBV adds
nothing on a bar with a missing close or on the next bar, which compares with
it, so its total stays offset by that step. One companion engine defect (PVT committed an overflowing
total) belonged to the companion engines and is corrected in their 0.7.2, and three comparison artifacts (the
slope reference, a newest-first CCI reference and the consolidation reference)
belong to the comparison harness. The wider comparison does not replace the independently
derived Hull and directional fixtures above or establish complete numerical
coverage.
