# Alppy — Design direction: "Encre violette"

These are shipped values, not suggestions. Copy them exactly. If `encre-violette.css` is ever
added to the repo it becomes the source of truth for tokens and recipes; until then the source of
truth is this file, reconstructed into `packages/ui/src/design/{tokens,base,motion,print}.css`.

Read this before writing any UI.

---

## 1. The stance

The *behaviour* borrows from Duolingo: thick buttons you physically press, progress rings
everywhere, generous radii, a celebration at the end. The *identity* comes from the subject: the
erasable violet ink pen every pupil in Suisse romande writes with, saturated chalk on a whiteboard,
and the slate.

Rules that are never broken:

- **Violet is ink, not a brand colour.** It is the primary, it tints the greys, and it is never
  decorative. It marks action.
- **The neutral leans toward the accent.** Canvas is `#F7F5FF`, not `#F7F7F7`. A pure grey reads as
  a default; a tinted grey reads as a choice.
- **Elevation is a solid edge, not a blur.** `0 4px 0 0 <edge>`. A button has physical thickness;
  you press down on it.
- **Mandarin orange is reserved for exactly one feature.** In Alppy that feature is **AI-generated
  exercises** (F4). It loses all meaning if it spreads.
- **Never pure black.** Text is `#1B1735`, a violet-black. Pure black appears only in high contrast
  and in print.
- **Never colour alone.** Every state band carries colour **and** a label **and** a different tint
  density. The photocopier is black and white.
- **No mascot.** Explicit decision.
- **No icon library, no font CDN.** Icons are drawn in the repo; fonts are self-hosted via
  `@fontsource-variable`.

---

## 2. Colour tokens

Each shade is declared once as `--c-*` on `:root`. No component ever writes a literal.

| Token | Light | Dark | Role |
|---|---|---|---|
| `--c-ink-900` | `#1B1735` | `#F4F2FF` | Primary text. Never pure black. |
| `--c-ink-700` | `#3A3560` | `#CFC9EC` | Secondary text, long body. |
| `--c-ink-500` | `#6B658F` | `#9C95C4` | Muted, captions. |
| `--c-ink-300` | `#A9A3C7` | `#6E679A` | Disabled, placeholders. |
| `--c-line` | `#E7E3F7` | `#342E5C` | Borders, card edges. |
| `--c-line-strong` | `#CDC6EA` | `#4A4280` | Secondary button edge. |
| `--c-surface` | `#FFFFFF` | `#1F1B3A` | Cards, panels, rail. |
| `--c-surface-2` | `#FBFAFF` | `#272247` | Sunken surface, table headers. |
| `--c-canvas` | `#F7F5FF` | `#151229` | Page background. |
| `--c-canvas-warm` | `#FFF8F0` | `#2A2033` | Celebration, rest states. |
| `--c-primary-500` | `#5B3FF0` | `#7C63FF` | The primary action. Heart of the DA. |
| `--c-primary-600` | `#4A32D9` | `#4E37C9` | Button edge, pressed state. |
| `--c-primary-700` | `#3A27AE` | `#6B4FFA` | Text on light tint. |
| `--c-primary-200` | `#D6CBFF` | `#3D3480` | Text selection, chip border. |
| `--c-primary-100` | `#ECE7FF` | `#2B2358` | Tints, focus halo. |
| `--c-primary-050` | `#F5F2FF` | `#221C46` | Ghost link hover. |
| `--c-accent-500` | `#FF8A3D` | `#FF9E5E` | One feature only: AI-generated content. |
| `--c-accent-600` | `#E06A22` | `#C96A28` | Accent button edge. |
| `--c-success-500` | `#00C48C` | `#24DBA2` | Correct, mastered. |
| `--c-warn-500` | `#FFC93C` | `#FFD264` | To review, flagged by AI. |
| `--c-danger-500` | `#FF5A5F` | `#FF7A7E` | Wrong, fading. |
| `--c-info-500` | `#3DB8FF` | `#63C8FF` | Neutral info, paper channel. |

Every state family exists in three steps, always the same: `-100` tinted background, `-500` full
colour, `-600` edge and text-on-tint. The derived steps are documented inline in `tokens.css`.

**Footer tokens** (`--c-foot-bg / -ink / -muted / -hair`) are separate and do **not** invert
between themes: the footer stays slate in both.

### The ordered domain scale

The most important colour decision in the product. Five mastery bands, used in the matrix (F3) and
everywhere mastery is shown. Never colour alone: always dot + label + tint density.

| Band | Threshold | Token | FR / DE / EN label |
|---|---|---|---|
| Solid — mastered | ≥ 0.90 | `--c-mastery-solid` | Acquis / Gefestigt / Solid |
| To review — due soon | 0.75 – 0.90 | `--c-mastery-ok` | À revoir / Bald fällig / To review |
| Fragile | 0.60 – 0.75 | `--c-mastery-weak` | Fragile / Unsicher / Fragile |
| Fading — losing it | < 0.60 | `--c-mastery-fading` | S'efface / Verblasst / Fading |
| Not yet seen | never assessed | `--c-mastery-none` | Pas encore vu / Noch nicht gesehen / Not yet seen |

---

## 3. Typography — four fonts, four roles

All self-hosted: `@fontsource-variable/{fredoka,nunito,jetbrains-mono,caveat}`, imported in the app
entry point. No CDN in production.

- **Display · Fredoka** (`--font-display`, 600/700): titles, ring numerals, celebration, **all
  button labels**.
- **UI & body · Nunito** (`--font-sans`, 400/600/700/800): everything else. Excellent French
  diacritics, friendly without being childish, readable projected.
- **Mono · JetBrains Mono** (`--font-mono`, 400): code, extracted/transcribed data. A transcription
  must look like data because the teacher audits it.
- **Hand · Caveat** (`--font-hand`): at most **once per page** — the accented word of a title, a
  handwritten equation. It is the chalk.

Scale, base 16 px (size / line-height / weight):

| Step | Value | Use |
|---|---|---|
| `display-2xl` | 4.25rem / 0.98 / 700 | Public landing hero only |
| `display-xl` | 3rem / 1.05 / 700 | |
| `display-l` | 2.25rem / 1.1 / 700 | Floor in projector mode |
| `h1` | 1.75rem / 1.2 / 700 | |
| `h2` | 1.375rem / 1.25 / 700 | |
| `h3` | 1.125rem / 1.3 / 700 | |
| `body-l` | 1.125rem / 1.6 | **Floor for any text a student sees (printed sheets)** |
| `body` | 1rem / 1.6 | |
| `body-s` | 0.875rem / 1.5 | Secondary info, field help, captions |
| `label` | 0.8125rem / 1.4 / 700 / uppercase / +0.04em | |

Global rules: `text-wrap: balance` on `h1..h4`; `tabular-nums` on `table, .tabular, [data-numeric]`;
student-facing text never below `body-l` — a product constraint, not a preference.

---

## 4. Space & shape — thick by default

- **Radii:** `sm 10px` (focus ring) · `md 16px` (buttons, panels, fields) · `lg 24px` (cards) ·
  `xl 32px` (sheets, modals) · `pill 999px` (chips, badges, gauges). Roles are fixed.
- **Spacing, base 4:** 2, 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96.
- **Elevation — a solid edge, never a blur alone:**
  - `--shadow-card: 0 2px 0 0 var(--c-line), 0 10px 30px -12px rgb(27 23 53 / .18)`
  - `--shadow-raised: 0 3px 0 0 var(--c-line-strong), 0 14px 34px -14px rgb(27 23 53 / .24)`
  - `--shadow-pop: 0 20px 50px -12px rgb(27 23 53 / .28)`
  - Button: `0 4px 0 0 var(--edge)` → hover `0 5px` + `translateY(-1px)` → pressed `0 1px` +
    `translateY(3px)`
  - `--focus-ring: 0 0 0 2px var(--c-primary-500), 0 0 0 6px var(--c-primary-100)`
- Dark theme: shadows shift from violet to black; primary rises ~8% in lightness. Dark is not an
  inversion.

---

## 5. Motion — four durations, two curves

| Token | Value | Use |
|---|---|---|
| `--t-fast` | 120 ms | press, hover, border change |
| `--t` | 200 ms | entrances, toasts, side panels |
| `--t-slow` | 320 ms | content appearance, error shake |
| `--t-celebrate` | 520 ms | delivery curtain, celebration |
| `--ease-out-soft` | `cubic-bezier(.2, .8, .2, 1)` | default: everything that arrives and settles |
| `--ease-spring` | `cubic-bezier(.34, 1.56, .64, 1)` | the bounce: pop-in and toast, nothing else |

Named `@keyframes` ship as `.anim-*` classes in `motion.css`. All motion is cut by
`prefers-reduced-motion` and `:root[data-motion="off"]` — **except** `[data-timer]`: a countdown the
user watches carries information; freezing it to 0 ms would tell them the window already closed.

---

## 6. Components — the four recipes

The whole system rests on four classes — `.ard-btn`, `.ard-card`, `.ard-panel`, `.ard-input` —
everything else composes with utilities.

- **Button:** solid edge collapses and the button drops onto it. Each variant sets its own `--edge`,
  one step darker than its face. Label in Fredoka 600, never Nunito. Minimum height = touch target,
  non-negotiable.
- **Card vs panel:** card = radius `lg` + solid edge + shadow (a separate object). Panel = radius
  `md` + border, no shadow (a subdivision of the same object). Do not put shadows everywhere. Card
  tints: default, primary, warm, success, warn, danger.
- **Chips / badges:** `-100` background, `-600` text, border = full colour at 40%. Type `label`.
  Variants: neutral, primary, success, warn, danger, info, accent. `ConceptTag` places the
  curriculum code in an outline pill — official data is never coloured.
- **Fields:** 2 px border (not 1 — the field must read as sunken), radius `md`, focus halo
  `0 0 0 4px var(--c-primary-100)`. Invalid state changes the border **and** adds a message — never
  colour alone.
- **ProgressRing:** SVG rotated −90°, drawn with `stroke-dashoffset`, centre numeral in Fredoka +
  `tabular-nums`. **MasteryMeter** (band gauge): pill with dot + label + "62 % · révision dans
  2 jours". **Toast:** the only place ink becomes the background.
- **Loading / empty / error:** `LoadingState` takes a `shape` that draws the shape of the coming
  page — a lone spinner says nothing about what is arriving. Every screen ships `EmptyState` and
  `ErrorState`.

Build order in `packages/ui`: primitives (Button, IconButton, Card, Panel, Chip, Badge, Pill,
Avatar, Divider, Tooltip, Popover, Modal, Sheet, Toast, Tabs, Stepper, Skeleton, EmptyState,
KeyboardHint), forms (Field, Input, Textarea, Select, Checkbox, Radio, Slider, Toggle,
SegmentedControl, CodeInput, RosterInput, FileDrop), then domain (ProgressRing, MasteryMeter,
MasteryCell/Matrix, MasteryCurve, ConceptTag, WorksheetPrintSheet, ProvenancePanel, ConfidenceBar,
ScanReviewOverlay, CelebrationOverlay).

Headless accessibility primitives (Radix or React Aria) are allowed for focus/ARIA behaviour; no
styled component kit, no shadcn theme, no lucide/heroicons.

---

## 7. Icons, illustrations, brand — everything drawn in the repo

- **Icons:** ~70 strokes on a 24 px grid, stroke 2–2.4 px, `stroke-linecap` and `stroke-linejoin`
  round, `currentColor` everywhere. Draw only what the MVP needs; no library, no borrowed marks.
- **Illustrations:** flat SVG, 120×120. Seven classroom objects (slate, compass, sheet, curve,
  clock, tray, cup). Three colours only: `primary-100` fill, `primary-500` stroke, `accent-500` for
  the single point of attention. Always `data-decorative` — calm mode removes them.
- **Brand mark:** a slate (rectangle, radius 7) crossed by a chalk stroke plus the mandarin dot,
  adapted for Alppy with an alpine notch in the chalk stroke. ~12 lines of SVG, drawn not licensed.
  The wordmark "Alppy" is Fredoka 700 beside the mark, never inside it.

---

## 8. Themes & accessibility — three states, not two

The default setting sets no attribute, so there are three cases, handled in this order:

```css
/* 1 · COMPLETE light palette on bare :root. Every variable exists here first. */
:root { --c-ink-900: #1b1735; /* … all tokens … */ }

/* 2 · dark when nothing was chosen. :not() lets an explicit "light" beat a dark system pref. */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme='light']) { --c-ink-900: #f4f2ff; /* … */ }
}

/* 3 · dark chosen explicitly — beats a light system preference. */
:root[data-theme='dark'] { --c-ink-900: #f4f2ff; /* … */ }

/* 4 · high contrast: a LAYER over either theme, driven by an independent attribute. */
:root[data-contrast='high'] { --c-ink-900: #000000; --border-w: 2px; /* … */ }
```

The four switches (product settings, persisted per teacher, applied as attributes on `:root`):

| Attribute | Values | Effect |
|---|---|---|
| `data-theme` | absent · `light` · `dark` | Palette. Absent = follow system. |
| `data-contrast` | absent · `high` | Pure black, 2 px borders. Independent of theme. |
| `data-motion` | absent · `off` | Cuts animations and transitions, except `[data-timer]`. |
| `data-calm` | absent · `on` | Reading mode: hides everything `[data-decorative]`. |

They compose: `data-theme="dark" data-contrast="high"` is a valid, tested state. No component is
ever written inside a theme block; `body` always paints its background explicitly; high contrast
thickens strokes too.

---

## 9. Print — paper is not a fallback

Sheets are photocopied and corrected on Sunday evening: they are the deliverable.

- A4 portrait, 14 mm margins: `@page { size: A4; margin: 14mm; }`.
- **The photocopier is black and white.** Every label carries a colour **and** a distinct underline
  (solid, dashed, dotted, double, wavy), and both appear in the legend.
- Rules at 0.5 pt minimum. No colour fill as the sole distinction between two columns.
- **One `.print-page` = one physical page**, not "one student's copy". Otherwise an overflowing copy
  produces a sheet with no header, no code, belonging to nobody.
- **Corner fiducials are real borders** (`[data-fiducial]`) so they survive the browser's default
  "no background graphics" setting. These same fiducials are what the scan pipeline (F2) uses for
  deskew and registration — the print layout and the detector are designed together and versioned
  together (`Sheet.layout_version`).
- **Always two sheets:** the blank version and the answer key.

```css
@media print {
  :root { --c-canvas: #fff; --c-surface: #fff; --c-ink-900: #000; --c-line: #999; }
  [data-no-print], nav, header[data-app-header] { display: none !important; }
  .print-page { page-break-after: always; break-after: page; box-shadow: none !important; }
  .print-item { break-inside: avoid; }
  [data-fiducial] { display: block !important; }
  @page { size: A4; margin: 14mm; }
}
```

The server-side PDF renderer consumes the **same** `print.css` and the same `WorksheetPrintSheet`
markup as the browser print preview, so what the teacher previews is what is printed.

---

## 10. Kit — wiring it in

1. Fonts: `@fontsource-variable/{fredoka,nunito,jetbrains-mono,caveat}`, imported in the entry file.
2. Four CSS files imported in this order from `index.css` — order matters, tokens must exist before
   base reads them:
   ```css
   @import 'tailwindcss';
   @import './design/tokens.css';  /* all tokens × 3 themes + the Tailwind bridge */
   @import './design/base.css';    /* element defaults — zero colour literals */
   @import './design/motion.css';  /* @keyframes + .anim-* classes */
   @import './design/print.css';   /* A4, 14 mm, fiducials */
   @layer components { /* the 4 recipes */ }
   ```
3. Tailwind v4 bridge — `@theme inline` keeps tokens as `var()`; without `inline` Tailwind freezes
   values at build time and live theme switching repaints nothing.
4. A lint rule (Stylelint + a small ESLint rule for inline styles) fails CI on any hex/rgb literal
   outside `tokens.css`.
