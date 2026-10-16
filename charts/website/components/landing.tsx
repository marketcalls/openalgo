import React from 'react';
import Link from 'next/link';
import BtcUsdChart from './BtcUsdChart';
import { highlight } from './highlight';

function Arrow({ diagonal = false }: { diagonal?: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d={diagonal ? 'M6 18 18 6M6 6h12v12' : 'M4 12h15m-6-6 6 6-6 6'} stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** A drawn mark for the list rows, so no row leans on a text character for its icon. */
function Mark({ kind }: { kind: 'detail' | 'theme' | 'open' }) {
  const d = kind === 'detail' ? 'M12 4v16M4 12h16M6.5 6.5l11 11M17.5 6.5l-11 11'
    : kind === 'theme' ? 'M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18v18' : 'M7 17 17 7M9 7h8v8';
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d={d} stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function Reveal({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <div className={`oac-reveal ${className}`}>{children}</div>;
}

export function Hero() {
  return (
    <section className="oac-hero" aria-labelledby="hero-title">
      <div className="oac-hero__copy">
        <div className="oac-eyebrow oac-intro oac-intro--eyebrow"><span className="oac-status-dot" /> THE OPENALGO CHARTING EXPERIENCE</div>
        <h1 id="hero-title" className="oac-hero__title">
          <span className="oac-title-line"><span className="oac-intro oac-intro--title">Every move.</span></span>
          <span className="oac-title-line"><span className="oac-intro oac-intro--gradient oac-gradient-text">A clearer view.</span></span>
        </h1>
        <p className="oac-hero__sub oac-intro oac-intro--sub">
          Go from watching the market to exploring it.<br className="oac-desktop-break" /> Beautiful charts. Powerful tools. A perspective that&rsquo;s yours.
        </p>
        <div className="oac-actions oac-intro oac-intro--actions">
          <a className="oac-action oac-action--primary" href="#playground">Try the live chart <Arrow /></a>
          <a className="oac-action oac-action--secondary" href="#possibilities">Explore the possibilities <Arrow diagonal /></a>
        </div>
      </div>
      <BtcUsdChart />
      <div className="oac-capability-strip" aria-label="Chart capabilities">
        <span>More ways to see the market</span>
        <div><strong>13</strong> chart types</div>
        <div><strong>112</strong> indicators</div>
        <div><strong>87</strong> drawing tools</div>
      </div>
    </section>
  );
}

type MiniBar = readonly [open: number, high: number, low: number, close: number];

const INDICATOR_BARS: readonly MiniBar[] = [
  [96, 99, 94, 98], [98, 100, 95, 97], [97, 101, 96, 100], [100, 102, 97, 99],
  [99, 103, 98, 101], [101, 104, 99, 100], [100, 102, 96, 97], [97, 100, 95, 99],
  [99, 104, 98, 103], [103, 106, 101, 105], [105, 107, 102, 104], [104, 109, 103, 108],
  [108, 111, 106, 110], [110, 112, 107, 109], [109, 114, 108, 113], [113, 117, 111, 116],
  [116, 118, 112, 114], [114, 117, 111, 115],
];
const EMA_VALUES = [96, 97, 98, 99, 99, 99, 99, 99, 100, 101, 102, 103, 104, 105, 106, 108, 109, 110];
const RSI_VALUES = [48, 52, 46, 54, 50, 47, 38, 44, 55, 62, 59, 68, 70, 63, 71, 76, 64, 68];
const DRAWING_BARS: readonly MiniBar[] = [
  [94, 98, 91, 96], [96, 99, 93, 95], [95, 100, 94, 98], [98, 101, 96, 100],
  [100, 103, 98, 99], [99, 103, 97, 102], [102, 105, 100, 104], [104, 107, 101, 102],
  [102, 108, 100, 106], [106, 109, 103, 107], [107, 110, 104, 105], [105, 111, 104, 109],
  [109, 112, 106, 108], [108, 115, 107, 113], [113, 116, 110, 112], [112, 117, 110, 115],
  [115, 118, 112, 114], [114, 119, 111, 117],
];

function miniPriceY(price: number): number { return 116 - (price - 90) * 3; }
function miniPath(values: readonly number[], y: (value: number) => number): string {
  return values.map((value, index) => `${index === 0 ? 'M' : 'L'}${18 + index * 18} ${y(value).toFixed(1)}`).join(' ');
}
function MiniCandles({ bars, muted = false }: { bars: readonly MiniBar[]; muted?: boolean }) {
  return <g opacity={muted ? 0.7 : 1}>{bars.map(([open, high, low, close], index) => {
    const x = 18 + index * 18;
    const top = Math.min(miniPriceY(open), miniPriceY(close));
    const color = close >= open ? '#31a99e' : '#e66c66';
    return <g key={index} fill={color} stroke={color}>
      <line x1={x} y1={miniPriceY(high)} x2={x} y2={miniPriceY(low)} strokeWidth="1.25" />
      <rect x={x - 3.5} y={top} width="7" height={Math.max(2, Math.abs(miniPriceY(open) - miniPriceY(close)))} strokeWidth="0" />
    </g>;
  })}</g>;
}

function FeatureArt({ type }: { type: 'indicators' | 'drawings' | 'views' }) {
  if (type === 'indicators') return (
    <div className="oac-feature-art oac-feature-art--indicators" aria-hidden="true">
      <span className="oac-art-label">PRICE / INDICATOR STUDY</span>
      <svg viewBox="0 0 360 175" fill="none">
        <path className="oac-art-grid" d="M0 28H360M0 72H360M0 116H360M0 143H360M72 0V175M144 0V175M216 0V175M288 0V175" />
        <MiniCandles bars={INDICATOR_BARS} />
        <path d={miniPath(EMA_VALUES, miniPriceY)} stroke="#d4ac63" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        <line x1="0" y1="122" x2="360" y2="122" stroke="var(--oac-card-border)" />
        <path d={miniPath(RSI_VALUES, value => 159 - (value - 30) * .62)} stroke="var(--oac-text)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        <text x="300" y="17" fill="#d4ac63" fontSize="9" fontWeight="700">EMA 20</text>
        <text x="18" y="138" fill="var(--oac-muted)" fontSize="9" fontWeight="700">RSI 14</text>
      </svg>
      <span className="oac-art-tag"><i /> Overlay + lower study</span>
    </div>
  );
  if (type === 'drawings') return (
    <div className="oac-feature-art oac-feature-art--drawings" aria-hidden="true">
      <span className="oac-art-label">DRAWING / SELECTED CHANNEL</span>
      <svg viewBox="0 0 360 175" fill="none">
        <path className="oac-art-grid" d="M0 28H360M0 72H360M0 116H360M72 0V175M144 0V175M216 0V175M288 0V175" />
        <MiniCandles bars={DRAWING_BARS} muted />
        <path d="M35 100 330 44 330 71 35 127Z" fill="var(--oac-text)" opacity=".085" />
        <path d="M35 100 330 44M35 127 330 71" stroke="var(--oac-text)" strokeWidth="2" strokeLinecap="round" />
        <path d="M35 114 330 58" stroke="#d4ac63" strokeWidth="1.4" strokeDasharray="5 5" opacity=".9" />
        <circle cx="35" cy="100" r="5" fill="var(--oac-card)" stroke="var(--oac-text)" strokeWidth="2" />
        <circle cx="330" cy="44" r="5" fill="var(--oac-card)" stroke="var(--oac-text)" strokeWidth="2" />
        <circle cx="35" cy="127" r="5" fill="var(--oac-card)" stroke="var(--oac-text)" strokeWidth="2" />
        <circle cx="330" cy="71" r="5" fill="var(--oac-card)" stroke="var(--oac-text)" strokeWidth="2" />
        <path d="m249 75 3 20 4-7 7-3Z" fill="var(--oac-text)" stroke="var(--oac-card)" strokeWidth="2" />
        <text x="39" y="152" fill="var(--oac-muted)" fontSize="9" fontWeight="700">2 PARALLEL BOUNDARIES</text>
      </svg>
      <span className="oac-art-tag"><i /> Selected channel · drag handles</span>
    </div>
  );
  return (
    <div className="oac-feature-art oac-feature-art--views" aria-hidden="true">
      <span className="oac-art-label">A different angle changes everything.</span>
      <div className="oac-art-views">
        <div className="oac-art-view oac-art-view--candles"><span>Candles</span><svg viewBox="0 0 110 96" fill="none"><path d="M15 43V86M36 35V73M57 40V78M78 15V57M99 3V43" stroke="var(--oac-accent-2)" /><path d="M15 52V76M36 42V65M57 49V68M78 24V46M99 13V33" stroke="var(--oac-accent-2)" strokeWidth="7" /></svg></div>
        <div className="oac-art-view oac-art-view--line"><span>Line</span><svg viewBox="0 0 110 96" fill="none"><path d="M0 80 15 70 25 74 39 49 49 59 62 33 75 41 86 19 97 25 110 7" stroke="var(--oac-accent)" strokeWidth="2" /></svg></div>
        <div className="oac-art-view oac-art-view--area"><span>Area</span><svg viewBox="0 0 110 96" fill="none"><path d="M0 80 15 70 25 74 39 49 49 59 62 33 75 41 86 19 97 25 110 7V96H0Z" fill="var(--oac-accent)" opacity=".15" /><path d="M0 80 15 70 25 74 39 49 49 59 62 33 75 41 86 19 97 25 110 7" stroke="var(--oac-accent)" strokeWidth="2" /></svg></div>
      </div>
      <span className="oac-art-tag">Find a view that speaks to you</span>
    </div>
  );
}

export function Features() {
  return (
    <section id="possibilities" className="oac-section oac-possibilities" aria-labelledby="possibilities-title">
      <Reveal className="oac-section-heading">
        <span className="oac-eyebrow">BUILT FOR YOUR CURIOSITY</span>
        <h2 id="possibilities-title">There&rsquo;s more to<br /><span className="oac-text-muted">every market move.</span></h2>
        <p>Follow the trend. Connect the dots. See what you couldn&rsquo;t see before.</p>
      </Reveal>
      <div className="oac-features">
        <Reveal className="oac-feature">
          <FeatureArt type="indicators" />
          <div className="oac-feature__copy"><span className="oac-feature__index">01 / DISCOVER</span><h3>Look beneath the surface.</h3><p>Bring price, momentum, and volatility into focus with 112 indicators. Layer your favorites and explore the bigger picture.</p><Link href="/examples#custom-indicators" className="oac-text-link">Explore indicators <Arrow /></Link></div>
        </Reveal>
        <Reveal className="oac-feature">
          <FeatureArt type="drawings" />
          <div className="oac-feature__copy"><span className="oac-feature__index">02 / EXPRESS</span><h3>Give your ideas a shape.</h3><p>Mark a level. Map a scenario. Tell the story you see with 87 drawing tools that put your thinking right on the chart.</p><Link href="/examples#drawing-tools" className="oac-text-link">Try the drawing tools <Arrow /></Link></div>
        </Reveal>
        <Reveal className="oac-feature">
          <FeatureArt type="views" />
          <div className="oac-feature__copy"><span className="oac-feature__index">03 / MAKE IT YOURS</span><h3>A fresh perspective, instantly.</h3><p>From the detail of candlesticks to the simplicity of a line. Find your rhythm with 13 chart types and a look that feels like you.</p><Link href="/examples#interactive" className="oac-text-link">Find your view <Arrow /></Link></div>
        </Reveal>
      </div>
    </section>
  );
}

export function WhyOpenSource() {
  return (
    <>
      <section className="oac-section oac-freedom" aria-labelledby="freedom-title">
        <Reveal className="oac-freedom__copy">
          <span className="oac-eyebrow">YOUR CHARTS. YOUR RULES.</span>
          <h2 id="freedom-title">Made to be<br /><span className="oac-gradient-text">made your own.</span></h2>
          <p>Your style. Your workflow. Your next big idea. OpenAlgo Charts gives you the freedom to create a charting experience that feels entirely yours.</p>
          <Link href="/examples" className="oac-text-link">See what&rsquo;s possible <Arrow diagonal /></Link>
        </Reveal>
        <Reveal className="oac-freedom__details">
          <div><span className="oac-freedom__icon" aria-hidden="true"><Mark kind="detail" /></span><div><h3>Every detail, considered.</h3><p>Thoughtful tools, fluid interaction, and room to focus on what matters to you.</p></div></div>
          <div><span className="oac-freedom__icon" aria-hidden="true"><Mark kind="theme" /></span><div><h3>At home in your world.</h3><p>Light or dark. A single chart or a complete workspace. Shape it around the way you work.</p></div></div>
          <div><span className="oac-freedom__icon" aria-hidden="true"><Mark kind="open" /></span><div><h3>Open from the start.</h3><p>Free to use, explore, and extend. Built in the open, for a community that keeps moving.</p></div></div>
        </Reveal>
      </section>
      <section className="oac-section oac-closing" aria-labelledby="closing-title">
        <Reveal>
          <span className="oac-eyebrow">A CHART IS JUST THE BEGINNING</span>
          <h2 id="closing-title">What will you see next?</h2>
          <p>Your next perspective is a click away.</p>
          <div className="oac-actions"><a href="#playground" className="oac-action oac-action--primary">Make your first move <Arrow /></a><Link href="/docs/getting-started" className="oac-action oac-action--secondary">Start creating <Arrow diagonal /></Link></div>
          <span className="oac-closing__wordmark" aria-hidden="true">OpenAlgo</span>
        </Reveal>
      </section>
    </>
  );
}

/**
 * A real chart screenshot in the site's theme. Both versions are in the page and
 * CSS shows the one that matches, so a theme switch needs no reload, and the
 * lazy image in the hidden theme is never fetched. Static export does not add
 * the base path to a plain img, so it is written out.
 */
function Shot({ name, alt, width, height }: { name: string; alt: string; width: number; height: number }) {
  const src = (theme: 'light' | 'dark') => `/openalgo-charts/home/${name}-${theme}.webp`;
  return (
    <figure className="oac-shot">
      <img className="oac-shot__img oac-shot__img--light" src={src('light')} alt={alt} width={width} height={height} loading="lazy" decoding="async" />
      <img className="oac-shot__img oac-shot__img--dark" src={src('dark')} alt={alt} width={width} height={height} loading="lazy" decoding="async" />
    </figure>
  );
}

const TREND_SYSTEMS = [
  { name: 'supertrend', title: 'Supertrend', text: 'An ATR band that flips colour where the trend turns.', data: 'LT daily, period 10, multiplier 3' },
  { name: 'halftrend', title: 'HalfTrend', text: 'A trend line inside its ATR channel, with buy and sell signals.', data: 'MARUTI daily, amplitude 2' },
  { name: 'alphatrend', title: 'AlphaTrend', text: 'The trend line and its lag, shaded between, with crossover signals.', data: 'SUNPHARMA daily' },
] as const;

export function TrendSystems() {
  return (
    <section className="oac-section oac-trends" aria-labelledby="trends-title">
      <Reveal className="oac-section-heading">
        <span className="oac-eyebrow">THE TREND SYSTEMS TRADERS ASK FOR</span>
        <h2 id="trends-title">Built in.<br /><span className="oac-text-muted">Drawn on real prices.</span></h2>
        <p>Supertrend, HalfTrend and AlphaTrend are part of the 112 indicators, not plugins, and each study draws its own signals.</p>
      </Reveal>
      <div className="oac-trend-grid">
        {TREND_SYSTEMS.map((t) => (
          <Reveal key={t.name} className="oac-trend">
            <Shot name={t.name} alt={`${t.title} on ${t.data}`} width={960} height={540} />
            <div className="oac-trend__copy"><h3>{t.title}</h3><p>{t.text}</p><span>{t.data}</span></div>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

const OPENSCRIPT_SAMPLE = `version 1

study("EMA cross", overlay = true, precision = 2)

fastLen = input(9,  "Fast length", min = 1, max = 500)
slowLen = input(21, "Slow length", min = 1, max = 500)
src     = input(close, "Source")

fast = ema(src, fastLen)
slow = ema(src, slowLen)
up   = crossUp(fast, slow)
down = crossDown(fast, slow)

fastPlot = plot(fast, "Fast", aqua, width = 2)
slowPlot = plot(slow, "Slow", orange, width = 2)
fill(fastPlot, slowPlot, fade(aqua, 90))

if up
    signal("BUY")
if down
    signal("SELL")`;

function Row({ id, eyebrow, title, children, link, href, media, flip = false }: {
  id: string; eyebrow: string; title: string; children: React.ReactNode;
  link: string; href: string; media: React.ReactNode; flip?: boolean;
}) {
  return (
    <Reveal className={`oac-row${flip ? ' oac-row--flip' : ''}`}>
      <div className="oac-row__media">{media}</div>
      <div className="oac-row__copy">
        <span className="oac-eyebrow">{eyebrow}</span>
        <h3 id={id}>{title}</h3>
        {children}
        <Link href={href} className="oac-text-link">{link} <Arrow /></Link>
      </div>
    </Reveal>
  );
}

export function Showcase() {
  return (
    <section className="oac-section oac-showcase" aria-labelledby="showcase-title">
      <Reveal className="oac-section-heading">
        <span className="oac-eyebrow">MORE THAN A CHART</span>
        <h2 id="showcase-title">Trade it. Replay it.<br /><span className="oac-text-muted">Script it.</span></h2>
        <p>Every picture below is the library itself, drawing real NSE prices.</p>
      </Reveal>
      <Row id="row-trading" eyebrow="TRADE FROM THE CHART" title="Orders you can see and drag." link="Chart trading" href="/docs/trading"
        media={<Shot name="trading" alt="SBIN 15 minute bars with a long position and its live P&L, a target, a stop and a resting buy order" width={1280} height={720} />}>
        <p>Order, stop and target lines sit on the price they belong to. Drag one to modify it, and watch the position line carry its live P&amp;L.</p>
        <ul>
          <li>Tick size, price band and freeze quantity are checked before an order leaves the chart.</li>
          <li>Everything starts in analyzer mode, the sandbox, until you choose live.</li>
          <li>The chart only proposes an order: your broker adapter is the one that sends it.</li>
        </ul>
      </Row>
      <Row id="row-replay" eyebrow="PRACTISE ON HISTORY" title="Replay a session, one minute at a time." link="Market replay" href="/docs/market-replay" flip
        media={<Shot name="replay" alt="RELIANCE 5 minute replay with HalfTrend, the current candle forming at step one of five" width={1280} height={679} />}>
        <p>Step or play through past sessions and watch each candle form from real one-minute bars, the way it did live.</p>
        <ul>
          <li>The open never moves, the high and low never pass the real candle&rsquo;s, and the last step lands on the real close.</li>
          <li>Where the source kept no finer history, the candle forms along a path through its own prices, and the replay bar says Simulated.</li>
          <li>Indicators, drawings and alerts replay with the chart.</li>
        </ul>
      </Row>
      <Reveal className="oac-script-block">
        <div className="oac-script-block__copy">
          <div>
            <span className="oac-eyebrow">OPENSCRIPT</span>
            <h3 id="row-openscript">Write a study once.<br />Plot it, backtest it, trade it.</h3>
          </div>
          <div>
            <p>OpenScript is an open trading language that runs on this chart. It compiles in the browser with no eval, a compiled program is plain data, and the same program runs on the TypeScript engine in the page and the Python engine on a server. A runaway script stops at its instruction, memory and time budgets.</p>
            <a href="https://github.com/marketcalls/openscript" className="oac-text-link" target="_blank" rel="noreferrer">OpenScript on GitHub, Apache-2.0 <Arrow diagonal /></a>
          </div>
        </div>
        <div className="oac-script">
          <pre className="oac-code-panel" aria-label="OpenScript source of the EMA cross study"><code dangerouslySetInnerHTML={{ __html: highlight(OPENSCRIPT_SAMPLE) }} /></pre>
          <div>
            <Shot name="openscript" alt="The EMA cross study compiled in the page and running on TITAN daily with lengths 20 and 50" width={1280} height={720} />
            <p className="oac-note">This script, compiled in the page and run on TITAN daily with lengths 20 and 50.</p>
          </div>
        </div>
      </Reveal>
      <Row id="row-structure" eyebrow="MARKET STRUCTURE" title="See where the volume traded." link="Profiles and order flow" href="/docs/profiles-and-orderflow" flip
        media={<Shot name="profile" alt="ICICIBANK 15 minute bars with a volume profile, its point of control and value area" width={1280} height={720} />}>
        <p>Volume Profile with its point of control and value area, Market Profile letter blocks, Footprint and cumulative delta, drawn inside the chart so they pan, zoom and change theme with it.</p>
      </Row>
    </section>
  );
}

const FRAMEWORKS = [
  ['JavaScript', 'plain-javascript'], ['CDN', 'plain-install'], ['React', 'react'], ['Next.js', 'nextjs'],
  ['Vue 3', 'vue-3'], ['Angular', 'angular'], ['Svelte', 'svelte'],
] as const;

const WIDGET_SAMPLE = `import { createWidget } from 'openalgo-charts/widget';
import 'openalgo-charts/indicators';
import { OpenAlgoDataFeed } from 'openalgo-charts';

const widget = createWidget('#terminal', {
  feed: new OpenAlgoDataFeed({ baseUrl, apiKey }),
  symbol: 'RELIANCE', exchange: 'NSE',
  interval: '5m', theme: 'light',
  onOrder: (order) => broker.place(order),
});`;

// Brotli sizes and release-bench frame times shown on the home page. They change
// with every release: CLAUDE.md lists them among the files a size change or a
// release benchmark updates.
const STATS = { release: '2.6.4', base: '137.65 kB', terminal: '364.04 kB' } as const;
const BENCH = { release: '2.6.4', pan: '2.1 ms', zoomOut: '55.3 ms', tick: '146.6 ms' } as const;

export function Integrate() {
  return (
    <section className="oac-section oac-integrate" aria-labelledby="integrate-title">
      <Reveal className="oac-integrate__copy">
        <span className="oac-eyebrow">INTEGRATE</span>
        <h2 id="integrate-title">Drop it into<br /><span className="oac-text-muted">your stack.</span></h2>
        <p>Nine tiers that load only when a screen needs them, no runtime dependencies, and one guide that covers every framework in the same depth.</p>
        <div className="oac-chips" aria-label="Framework guides">{FRAMEWORKS.map(([name, anchor]) => <Link key={name} href={`/docs/frameworks/#${anchor}`} className="oac-chip">{name}</Link>)}</div>
        <dl className="oac-sizes">
          <div><dt>{STATS.base}</dt><dd>the base engine</dd></div>
          <div><dt>{STATS.terminal}</dt><dd>a complete terminal</dd></div>
          <div><dt>0</dt><dd>runtime dependencies</dd></div>
        </dl>
        <p className="oac-note">Sizes are Brotli-compressed, measured for {STATS.release}.</p>
        <Link href="/docs/getting-started" className="oac-text-link">Get started <Arrow /></Link>
      </Reveal>
      <Reveal className="oac-integrate__code">
        <pre className="oac-code-panel" aria-label="Create the whole terminal in one call"><code dangerouslySetInnerHTML={{ __html: highlight(WIDGET_SAMPLE) }} /></pre>
        <p className="oac-note">The widget never sends an order itself: onOrder hands each one to your code.</p>
      </Reveal>
    </section>
  );
}

export function Performance() {
  return (
    <section className="oac-section oac-performance" aria-labelledby="performance-title">
      <Reveal className="oac-section-heading">
        <span className="oac-eyebrow">MEASURED ON EVERY RELEASE</span>
        <h2 id="performance-title">Fast on deep history.</h2>
        <p>95th percentile frame times on 200,000 bars with Canvas 2D, from the {BENCH.release} release bench.</p>
      </Reveal>
      <Reveal className="oac-stats">
        <div><strong>{BENCH.pan}</strong><span>a pan frame</span></div>
        <div><strong>{BENCH.zoomOut}</strong><span>a full zoom-out, every bar in view</span></div>
        <div><strong>{BENCH.tick}</strong><span>a live tick with ten studies</span></div>
      </Reveal>
      <Reveal className="oac-performance__link"><Link href="/benchmarks" className="oac-text-link">Every release&rsquo;s benchmark <Arrow /></Link></Reveal>
    </section>
  );
}

export function BuiltForIndia() {
  return (
    <section className="oac-section oac-india" aria-labelledby="india-title">
      <Reveal className="oac-row">
        <div className="oac-row__media"><Shot name="intraday" alt="RELIANCE 5 minute bars over three sessions with session VWAP and its bands, Supertrend and volume" width={1280} height={720} /></div>
        <div className="oac-row__copy">
          <span className="oac-eyebrow">MADE FOR INDIAN MARKETS</span>
          <h3 id="india-title">Indian defaults. Your brand.</h3>
          <ul>
            <li>IST by default, and any IANA timezone when you need another.</li>
            <li>Intraday candles on the NSE session grid, anchored to the 09:15 open.</li>
            <li>Price-dependent tick sizes for orders, alerts and dragged lines.</li>
            <li>History, live ticks and orders through OpenAlgo&rsquo;s 36 broker plugins.</li>
            <li>Light and dark themes, every colour configurable, and your own logo.</li>
          </ul>
          <Link href="/docs/openalgo-compatibility" className="oac-text-link">Connect to OpenAlgo <Arrow /></Link>
        </div>
      </Reveal>
    </section>
  );
}
