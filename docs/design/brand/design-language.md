# Brand and Design Language

Date: 2026-10-17
Status: All brand decisions approved (D1 to D6). Product name: FastAlgo. M1.1 assets done, and M1.2 spec approved. Next: the code foundation (M1.3).
Milestones: M1.1 (brand identity) and M1.2 (design language spec), from `docs/plans/2026-10-17-product-rebrand-review.md`.

---

## 1. Brand context

- **Maker.** An independent freelance practice for Indian traders and small businesses, currently branded TinyCompute (https://www.tinycompute.site/). No company is formed, and the maker's name and domain may change.
- **Product address.** `<productname>.<makerdomain>.site`, today `fastalgo.tinycompute.site`.
- **Consequence.** The product name must stand on its own, without "TinyCompute" in it. The maker's name and domain live in configuration (`brand.ts`: `makerName`, `makerUrl`, `productUrl`), so a domain change is a config edit, not a rebrand.
- **The maker's voice.** "Seedhi Baat": direct, friendly, jargon-free, honest about cost, and comfortable with Hinglish. The product inherits that tone.
- **Audience.** Indian retail and semi-professional traders who pay the maker to set up and run their strategies. They are not developers.

---

## 2. Product name

### 2.1 Criteria

- It signals speed, efficiency, quickness or success.
- It works as a subdomain: short, lowercase, no hyphen, easy to spell when heard on a phone call.
- It is easy for Indian traders to say and remember.
- It avoids the names of brokers already supported, such as Arrow, Dhan and Groww, and of well-known Indian trading products (Streak, Tradetron, Sensibull, AlgoTest and similar).
- It promises no profit. A name may suggest success, but it must not read as a return guarantee. SEBI is strict about implied returns in marketing to retail traders.

### 2.2 Candidates (revision 2: English names that say "algo")

The owner asked for an English name that tells users straight away that this is algo trading, in the style of Fast Trade, Falcon Trade or Fast Algo Trade. The first round of names (QuickFill, Sarpat, Phurti, TezAlgo and others) was set aside for that reason.

| Name | Subdomain | Meaning | Strengths | Watch out for | Web check (2026-10-17) |
| --- | --- | --- | --- | --- | --- |
| **FalconAlgo** | `falconalgo` | The peregrine falcon is the fastest animal on earth. "Algo" says what it does | Speed and precision in one image, plus "algo" in the name. Distinctive enough to own. Gives the brand a natural symbol | "Falcon" is common in unrelated fintech, such as fraud-detection products. Fine as a full name, weak as "Falcon" alone | No trading product found by that name |
| **FastAlgo** | `fastalgo` | Exactly what it says | The clearest possible name. The owner's own idea. Short | Purely descriptive, so it is hard to protect and easy for others to imitate. Sounds generic next to competitors | No trading product found by that name |
| **AlgoDash** | `algodash` | "Dash" means a sprint, and also a dashboard | A double meaning that fits the product, which is a dashboard that executes quickly | "Dash" is also a cryptocurrency, so search results mix in Algorand/Dash pairs | No trading product found. Results show crypto pairs only |
| **AlgoSprint** | `algosprint` | Sprint: short, fast burst | Energetic, clearly "algo" | Longer to say. "Sprint" is also a US phone brand | No product found |
| **FalconTrade** | `falcontrade` | Falcon plus trade | Speed image, simple | Does not say "algo", so it reads as a manual trading app | No India product found |
| **Fast Trade** | `fasttrade` | Fast plus trade | Very plain | Does not say "algo". Too generic to stand out. Fast-execution apps already crowd this space (Flash by INDstocks, Jiffy by Choice Broking) | Similar speed-themed apps exist |
| **Fast Algo Trade** | `fastalgotrade` | Fast plus algo plus trade | Fully descriptive | Three words is too long for a subdomain, a logo or a support call. Shorten to FastAlgo | Not checked separately |
| ~~SwiftAlgo~~ | | Swift plus algo | | **Rejected.** "Swift Algo" is an existing signals product with mixed reviews, and one review site calls it a scam. The association would hurt us | Existing product found |

The web checks are simple Google-style searches, not trademark searches. The Indian trademark registry (ipindiaonline.gov.in, classes 9 and 36) and the Play Store still need to be checked for the chosen name before any assets are made.

Sources: [Swift Algo on Trustpilot](https://pt.trustpilot.com/review/www.swiftalgo.net), [Swift Algo X on TradingView](https://de.tradingview.com/script/rlAUEVcs-Swift-Algo-X), [Flash Trading App by INDstocks](https://apps.apple.com/app/id6474673274), [Jiffy by Choice Broking](https://alternativeto.net/software/jiffy-trading-app--india-s-best-stock-market-app/about).

### 2.3 Recommendation

1. **FalconAlgo** (first choice). It is the only name on the list that is fast, clearly algo, and distinctive enough to stand out and be protected. It also gives the brand a symbol: the falcon's dive, which is the fastest motion in nature. The approved forward-chevron mark reads naturally as a falcon stooping on its target, so the logo concept (D4) needs no change. In a support call: "open FalconAlgo and check your positions".
2. **FastAlgo** (if plainness matters most). It says exactly what the product is, at the cost of being generic and hard to protect.
3. **AlgoDash** (if you like the dashboard double meaning).

The subdomain is always available, since you own the parent domain.

**Decided 2026-10-17: FastAlgo.** The owner chose plainness: the name says exactly what the product does. The trade-off is accepted. A descriptive name is hard to protect as a trademark, which matters little for a services business. Still to do: a quick check of the Indian trademark registry and the Play Store for "FastAlgo", to make sure nobody uses it for trading software.

### 2.4 Name system

| Use | Form | FastAlgo |
| --- | --- | --- |
| Product name | One word, capital F and A | FastAlgo (never "Fast Algo", "Fastalgo" or "FASTALGO") |
| Wordmark | Lowercase, one word | fastalgo |
| Short name (browser tab, PWA, tight spaces) | The name, or its initials where space is very tight | FastAlgo, or FA |
| Address | `<name>.<makerdomain>.site` | fastalgo.tinycompute.site |
| Endorsement line | `<Product> by <makerName>` | FastAlgo by TinyCompute |
| Attribution (About page and footer) | Fixed text | Based on OpenAlgo, licensed under AGPL-3.0 |
| White-label (Q6) | `<Client display name>`, powered by `<Product>` | Sharma Capital, powered by FastAlgo |
| Tagline (D5) | Fixed text | Automate your trading strategy. Take fast trades. |

### 2.4a White-label setup (per client installation)

Implemented in M1.3. On the client's server, create `custom_brand/` at the repo root (it is gitignored, so updates never touch it):

```
custom_brand/
  brand.json       {"displayName": "Sharma Capital", "logo": "sharma.png"}
  sharma.png       square image, 512 px recommended (png, svg, jpg or webp)
```

Reload the page and the client's name and logo appear. No rebuild or restart is needed.

- Only the display name (up to 60 characters), the logo and the Telegram support link can change. The product name, the attribution and the source link stay, as AGPL requires.
- Telegram support link: add `"supportTelegramUrl": "https://t.me/<username>"` to `brand.json`. Without it, the footer and the About page link to the default in `brand.ts` and `utils/brand.py` (`https://t.me/RanjT55`). Only an `https://t.me/` username link is accepted; anything else falls back to the default.
- The footer and About line become "Sharma Capital, powered by FastAlgo".
- If `brand.json` is missing or invalid, or the logo file is not there, the app quietly shows the normal FastAlgo brand. A bad override can never break the login page.
- How it works: Flask serves the override as `/brand-config.js` (`blueprints/react_app.py`), which loads before the React app. The React app reads it in `frontend/src/brand/brand.ts`.

Wordmark detail: in `fastalgo`, the letters "fast" are set in Ink (near-white on dark), and "algo" is set in the same colour at regular weight, against bold for "fast". The weight change keeps the two words readable inside one lowercase word without adding a second colour next to the teal mark.

### 2.5 Tagline candidates

Taglines describe speed and control. None promises returns.

- "Automate your trading strategy. Take fast trades."
- "From signal to order, without the wait."
- "Seedhi strategy. Tez execution." (Hinglish, for marketing pages only)
- "Set it up once. Trade it every day."

---

## 3. Design principles for a safe reskin

These rules exist so the reskin cannot break a working screen.

1. **Change the tokens, not the components.** The colour work happens in the CSS variables in `frontend/src/index.css` (the unlayered `:root` and `.dark` blocks). Components already read those variables, so every page changes at once and no layout code is touched.
2. **Never touch profit, loss, buy or sell colours.** About 1,750 Tailwind colour classes (`text-green-600`, `bg-red-500` and similar) are written directly into components, mostly for profit/loss and buy/sell. They stay exactly as they are. The brand palette is chosen so it never resembles them.
3. **Keep the mode colours.** Analyzer mode (purple, the `.analyzer` blocks) and sandbox mode (amber, `.sandbox`) are safety signals: they tell a trader that orders are not live. Their blocks in `index.css` stay unchanged.
4. **Keep text widths unchanged.** The UI uses the operating system's font today. Changing the body font changes the width of every label, and dense screens (option chain, scalping, positions, order book) could truncate or wrap. Phase 1 keeps the system font for the UI and expresses the brand through the logo, which is a vector drawing that needs no font.
5. **Hold contrast at WCAG AA.** Body text needs at least 4.5:1 against its background, and large text and UI borders at least 3:1. Every token pair in section 4 is chosen to meet that, and M1.6 verifies it on screen.
6. **No emojis or decorative icons in product text.** This is a repository rule (`CLAUDE.md`), and it also suits the product's straightforward voice. Functional UI icons (lucide-react) stay.

---

## 4. Design tokens

### 4.1 The palette idea: Ink and Pulse

- **Ink.** A deep blue-black for text and primary buttons. It reads as precise and trustworthy, and it keeps primary buttons visually distinct from the green and red trade buttons.
- **Pulse.** An electric teal used as the brand accent: focus rings, the active sidebar item, the logo, links, chart series 1 and the browser theme colour. Teal sits on the hue wheel between profit green and buy blue without matching either. It reads as speed and technology.
- **Cool neutrals.** Backgrounds, cards and borders get a slight blue tint (chroma 0.002 to 0.02), instead of today's pure grey. It is subtle, but it is what makes the product look like its own thing.

Hue map: profit green ~145, Pulse teal 195, buy blue ~250, Ink 255, analyzer purple 280, sandbox amber ~85, loss red ~25. Pulse is the only brand hue, and it overlaps none of the semantic hues.

### 4.2 Core palette

The CSS uses the OKLCH values. The hex values are their sRGB conversions, for design tools and the logo.

| Token | OKLCH | Hex | Use |
| --- | --- | --- | --- |
| ink-950 | `oklch(0.18 0.02 255)` | `#0C121A` | Text (light mode), dark mode background family |
| ink-800 | `oklch(0.26 0.04 255)` | `#162537` | Primary buttons (light mode), logo tile |
| ink-500 | `oklch(0.50 0.02 255)` | `#5C646F` | Secondary text (light mode) |
| mist-100 | `oklch(0.965 0.006 250)` | `#F0F4F7` | Muted surfaces (light mode) |
| mist-200 | `oklch(0.915 0.008 250)` | `#DFE3E8` | Borders (light mode) |
| pulse-600 | `oklch(0.50 0.11 195)` | `#007677` | Teal text and teal fills that carry white text (light mode): links, active sidebar item |
| pulse-500 | `oklch(0.62 0.13 195)` | `#009D9E` | Non-text accent on light backgrounds: focus ring, chart series 1 |
| pulse-300 | `oklch(0.78 0.12 195)` | `#3BCFCF` | Accent on dark backgrounds, logo chevrons |
| pulse-50 | `oklch(0.955 0.02 195)` | `#E2F5F4` | Hover and selected rows (light mode) |

**Rule:** in light mode, pulse-500 is never used for text or behind white text. It measures 3.2:1, which is enough for a focus ring or a chart line (3:1 needed) but not for text (4.5:1 needed). Use pulse-600 instead.

### 4.2a Measured contrast

| Pair | Ratio | Needed |
| --- | --- | --- |
| ink-950 text on light background | 18.3 | 4.5 |
| ink-500 secondary text on mist-100 | 5.4 | 4.5 |
| White text on ink-800 primary button | 15.5 | 4.5 |
| White text on pulse-600 (active sidebar item) | 5.5 | 4.5 |
| pulse-600 link text on light background | 5.3 | 4.5 |
| ink-800 text on pulse-50 hover row | 13.7 | 4.5 |
| pulse-500 focus ring on light background | 3.2 | 3.0 |
| Dark foreground on Midnight background | 17.9 | 4.5 |
| Dark muted text on dark muted surface | 6.0 | 4.5 |
| Ink text on near-white dark-mode primary button | 15.7 | 4.5 |
| ink-950 text on pulse-300 (dark active sidebar item) | 9.9 | 4.5 |
| pulse-300 ring on Midnight background | 10.3 | 3.0 |

These were computed from the OKLCH values (sRGB, WCAG 2 formula). M1.6 confirms them on screen.

### 4.3 Light mode (replaces the unlayered `:root` block)

```css
:root {
  --radius: 0.5rem;
  --background: oklch(0.99 0.002 250);
  --foreground: oklch(0.18 0.02 255);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.18 0.02 255);
  --popover: oklch(1 0 0);
  --popover-foreground: oklch(0.18 0.02 255);
  --primary: oklch(0.26 0.04 255);
  --primary-foreground: oklch(0.985 0 0);
  --secondary: oklch(0.965 0.006 250);
  --secondary-foreground: oklch(0.26 0.04 255);
  --muted: oklch(0.965 0.006 250);
  --muted-foreground: oklch(0.50 0.02 255);
  --accent: oklch(0.955 0.02 195);
  --accent-foreground: oklch(0.26 0.04 255);
  --destructive: oklch(0.577 0.245 27.325);
  --border: oklch(0.915 0.008 250);
  --input: oklch(0.915 0.008 250);
  --ring: oklch(0.62 0.13 195);
  --chart-1: oklch(0.62 0.13 195);
  --chart-2: oklch(0.55 0.16 265);
  --chart-3: oklch(0.77 0.16 75);
  --chart-4: oklch(0.60 0.20 340);
  --chart-5: oklch(0.55 0.03 255);
  --sidebar: oklch(0.975 0.004 250);
  --sidebar-foreground: oklch(0.18 0.02 255);
  --sidebar-primary: oklch(0.50 0.11 195);
  --sidebar-primary-foreground: oklch(0.99 0 0);
  --sidebar-accent: oklch(0.955 0.02 195);
  --sidebar-accent-foreground: oklch(0.26 0.04 255);
  --sidebar-border: oklch(0.915 0.008 250);
  --sidebar-ring: oklch(0.62 0.13 195);
}
```

### 4.4 Dark mode, "Midnight" (replaces the unlayered `.dark` block)

```css
.dark {
  --background: oklch(0.155 0.015 255);
  --foreground: oklch(0.97 0.005 250);
  --card: oklch(0.195 0.018 255);
  --card-foreground: oklch(0.97 0.005 250);
  --popover: oklch(0.195 0.018 255);
  --popover-foreground: oklch(0.97 0.005 250);
  --primary: oklch(0.95 0.01 250);
  --primary-foreground: oklch(0.20 0.025 255);
  --secondary: oklch(0.25 0.018 255);
  --secondary-foreground: oklch(0.97 0.005 250);
  --muted: oklch(0.25 0.018 255);
  --muted-foreground: oklch(0.70 0.015 250);
  --accent: oklch(0.27 0.03 200);
  --accent-foreground: oklch(0.97 0.005 250);
  --destructive: oklch(0.704 0.191 22.216);
  --border: oklch(1 0 0 / 10%);
  --input: oklch(1 0 0 / 15%);
  --ring: oklch(0.78 0.12 195);
  --chart-1: oklch(0.78 0.12 195);
  --chart-2: oklch(0.68 0.15 265);
  --chart-3: oklch(0.80 0.15 75);
  --chart-4: oklch(0.70 0.18 340);
  --chart-5: oklch(0.70 0.03 250);
  --sidebar: oklch(0.175 0.016 255);
  --sidebar-foreground: oklch(0.97 0.005 250);
  --sidebar-primary: oklch(0.78 0.12 195);
  --sidebar-primary-foreground: oklch(0.18 0.02 255);
  --sidebar-accent: oklch(0.25 0.025 205);
  --sidebar-accent-foreground: oklch(0.97 0.005 250);
  --sidebar-border: oklch(1 0 0 / 10%);
  --sidebar-ring: oklch(0.78 0.12 195);
}
```

Why dark-mode primary stays near-white: today's dark primary is near-white too, so every button, badge and selected tab keeps the contrast it was designed with. The brand shows through the ring, the sidebar, the hover tint and the logo. A bolder option is to make dark-mode primary Pulse teal with Ink text. That can be tried in M1.6 after a visual check of the order screens, but it is not the default.

### 4.5 What stays untouched

| Item | Location | Reason |
| --- | --- | --- |
| Analyzer theme | `.analyzer` blocks in `index.css` | Safety signal for paper trading (Q2) |
| Sandbox theme | `.sandbox` block | Safety signal |
| Profit, loss, buy, sell | Hard-coded Tailwind classes and the `--profit`, `--loss`, `--buy`, `--sell` variables | Trading semantics. Changing them risks a misread trade |
| Destructive red | `--destructive` | Already correct, and close to the loss colour by design |
| Flow editor styles | `.react-flow__*` rules | Keep as is, and review only in M1.6 |
| Chart candle colours | `lib/trading/chartTheme.ts` | Up and down candles carry trading meaning. Only the surface and grid follow the tokens |

### 4.6 Accent-colour picker (Q2)

The `[data-theme="green"]`, `"blue"` and other blocks let a user pick an accent. Under Q2 the picker is removed from the UI and the default (no `data-theme` override) is used, so the brand tokens always apply. The CSS blocks can stay until Phase 2 cleanup. With the picker gone, nothing selects them.

### 4.7 Shape, type and spacing

| Token | Value | Change from today |
| --- | --- | --- |
| Radius | `--radius: 0.5rem` | From 0.625rem. Slightly sharper, which reads as more precise. Purely visual |
| UI font | System stack (unchanged) | None. Protects every layout (principle 4) |
| Numbers | `font-variant-numeric: tabular-nums` on prices, quantities and P&L cells | New. Digits share one width, so columns line up and values stop jittering on live ticks. Width per digit changes slightly, so check dense tables in M1.6 |
| Monospace | Existing stack at `index.css` line 737 | None |
| Spacing | Tailwind scale (unchanged) | None. Layout stays |

### 4.8 Browser and page metadata

| Item | Value |
| --- | --- |
| `<title>` | Product name, from `brand.ts` through `usePageTitle` |
| `theme-color` meta (today `#3b82f6`) | `#162537` (ink-800) |
| Favicon, touch icon, `logo.png` | Generated from the mark in section 5 |

---

## 5. Logo

### 5.1 Concept: the forward tick

Two nested corner chevrons point up and to the right, the direction a trader reads as both "faster" and "higher". The inner chevron is lighter, like a motion trail. They sit on a rounded Ink tile.

- It works without the name, so it serves as the favicon, app icon and loading mark.
- It works for any of the candidate names.
- It is drawn as vector shapes, so it needs no font and stays sharp at 16 px and 512 px.

### 5.2 Draft mark (SVG)

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Product mark">
  <rect width="64" height="64" rx="14" fill="#162537"/>
  <path d="M16 28H36V48" fill="none" stroke="#3BCFCF" stroke-opacity="0.5" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M26 16H48V38" fill="none" stroke="#3BCFCF" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
```

**Final (M1.1, 2026-10-17).** The draft geometry above was kept unchanged. The full set lives in `frontend/src/brand/assets/` and is generated by `scripts/brand/build_brand_assets.py`:

| Asset | Size | Content |
| --- | --- | --- |
| `fastalgo-mark.svg` | Vector | Tile and chevrons |
| `fastalgo-glyph.svg` | Vector | Chevrons only in pulse-500, transparent, cropped to the strokes. Used for chart watermarks |
| `fastalgo-wordmark-light.svg`, `fastalgo-wordmark-dark.svg` | Vector | Mark plus "fastalgo" in outlines |
| `logo.png` | 512 px | Mark |
| `android-chrome-192x192.png` | 192 px | Mark |
| `apple-touch-icon.png` | 180 px | Full-bleed Ink square, chevrons at 86% so iOS corner rounding never clips them |
| `favicon.ico` | 16, 32, 48 px | Mark, each size rendered separately at 16x supersampling |

The set was checked in a browser render (headless Edge) on light and dark backgrounds. That covered the navbar size (32 px), the login size (80 px), the Flow editor size (24 px) and the chart watermark sizes (15 and 22 px). The favicon was inspected pixel by pixel at 16, 32 and 48 px, and the chevrons stay distinct at 16 px.

### 5.3 Wordmark

- The name is set in lowercase in Manrope (SIL Open Font License 1.1), "fast" at weight 800 and "algo" at weight 500, with -1% tracking, then converted to outlines. The app never loads the font. The ascender height equals 36/64 of the tile, centred on it, with a 16-unit gap after the tile.
- Ink on light backgrounds, near-white on dark. The mark keeps its teal chevrons on both.
- Clear space around the logo equals the height of the tile's corner radius on every side.

---

## 6. Voice and wording

| Principle | Do | Don't |
| --- | --- | --- |
| Plain, direct English in the app | "Your broker session has expired. Log in again to keep trading." | "Session invalid (401)" |
| Name the next action | "Add your API key under Broker settings." | "Configuration error." |
| Hinglish only in marketing, never in app text | Landing page tagline: "Seedhi strategy. Tez execution." | Hinglish button labels |
| No return promises | "Runs your strategy the moment the signal arrives." | "Make more profit", "guaranteed" |
| Calm about money | "Order rejected by your broker: insufficient funds." | Exclamation marks, alarm wording |
| Credit the maker lightly | Footer: "FastAlgo by TinyCompute" | The maker's name on every screen |

This follows the repository's existing rule that every message is written for a trader, not a developer (`CLAUDE.md`).

---

## 7. Application checklist (for M1.3 to M1.6)

1. Replace the unlayered `:root` and `.dark` blocks in `frontend/src/index.css` with sections 4.3 and 4.4. Leave the `@layer base` HSL block, `.analyzer`, `.sandbox`, the `[data-theme]` blocks and the React Flow rules alone.
2. Remove the accent-colour picker from the UI (4.6).
3. Add `tabular-nums` to the shared table and price components (4.7).
4. Replace `logo.png`, `favicon.ico` and `apple-touch-icon.png` in `frontend/public/`, and update `<title>` and `theme-color` in `frontend/index.html` (4.8, 5.2).
5. Visual check of every navigation page in light mode, dark mode, analyzer mode and sandbox mode. Look specifically at the option chain, scalping terminal, positions, order book, Flow editor and charts.
6. Check contrast with a browser accessibility tool on the login page, dashboard and one dense table in both themes.

---

## 8. Decisions needed from the owner

| # | Decision | Status |
| --- | --- | --- |
| D1 | Product name | Approved 2026-10-17: **FastAlgo** (section 2.4). Trademark registry and Play Store check pending |
| D2 | Palette direction: Ink and Pulse teal | Approved 2026-10-17 |
| D3 | Dark-mode primary | Approved: near-white now, teal to be tried in M1.6 |
| D4 | Logo concept: forward tick (nested chevrons) | Approved. Final assets after D1 |
| D5 | Tagline | Approved, changed by the owner on 2026-10-17: "Automate your trading strategy. Take fast trades." (was "Your strategy, executed fast.") |
| D6 | Endorsement wording | Approved: "<Product> by <makerName>", taken from config |
