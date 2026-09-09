# Design constraints — the DC register

**What this is.** [`DESIGN.md`](../../DESIGN.md) says what the system *is*.
[`decisions-log.md`](../decisions-log.md) says *why* each choice was made (D1…D47).
This file is the third leg: the rules that are **load-bearing** — the ones where a
plausible-looking change quietly breaks the product — each with an identifier, the
thing that actually enforces it, and the symptom you would see if it were violated.

Three kinds of statement, and they are not interchangeable:

| | Answers | Lives in | Changing it means |
|---|---|---|---|
| **Token / spec** | "what value?" | `DESIGN.md`, `tokens.css` | edit the token |
| **Decision `Dn`** | "why this way?" | `decisions-log.md` | add a new `Dn` |
| **Constraint `DC-*`** | "what must never break?" | **this file** | see [Changing a constraint](#changing-a-constraint) |

**The failure-symptom column is the point.** A constraint whose violation has no
describable symptom is a preference, and preferences do not belong here. If you cannot
fill that column, the rule goes in `DESIGN.md` as a spec instead.

**Enforced in** is honest, not aspirational. `review only` means exactly that: nothing
in CI will catch it, so it is on the reader of the diff. Those are the expensive ones.

---

## How to cite a constraint

When code exists *because of* a constraint — and would look arbitrary or over-built
without it — name the constraint in a comment. This is for the non-obvious cases; do
not sprinkle citations on code that is self-evident.

```css
/* DC-shape-01: panel is a subdivision, not an object — border, no shadow. */
.ard-panel { border-radius: var(--r-md); border: 1px solid var(--c-line); }
```

```tsx
{/* DC-colour-06: the accent means AI-generated content and nothing else. */}
<AiBadge />
```

```python
# DC-print-07: layout numbers are versioned — a change here is a layout version
# bump, because old scans must keep registering against the layout they printed with.
ITEMS_TOP_MM = 62.0
```

`rg 'DC-[a-z]+-\d\d'` then tells you every place a rule is load-bearing — which is what
you want before you touch it.

---

## 1 · Brand — `DC-brand-*`

Source: `DESIGN.md` §7, [`README.md`](README.md), `Alppy-identite-visuelle.pdf`.
Governing rule: **the shipped assets outrank any prose, including `DESIGN.md`** (D19).

| # | Constraint | Enforced in | Failure symptom |
|---|---|---|---|
| DC-brand-01 | The mark is **"Le sourire"** — two slopes meeting at a summit, the smile is the crossbar of the **A**. Import from `alppy-brand-assets/brand/logo/`; never redraw it. | review only | Two marks in circulation, neither of them the one in the manual. |
| DC-brand-02 | **The mark carries no mandarin accent.** | review only | The accent stops meaning AI-generated content (see DC-colour-06). |
| DC-brand-03 | Never stretch, recolour, rotate or shadow the mark. | review only | The identity reads as clip-art. |
| DC-brand-04 | Below 24 px use `alppy-mark-small.svg` (smile lifted to 34.0u, opened). | review only | The smile closes into a blot; the mark becomes a violet smudge in the tab. |
| DC-brand-05 | Wordmark **beside** the mark, never inside. Cap height 0.62 of mark height, aligned on the cap band, not the bounding box. Clear space 1/4 mark height. | review only | The descenders in *pp* and *y* pull the wordmark visibly low. |
| DC-brand-06 | Pictogram stroke is **2.2 — never 2, never 3.** | `generate-icons.py` writes the attribute | An icon set that is subtly two weights. |
| DC-brand-07 | Pictograms are line drawings in `currentColor`. Solid fill is reserved for dots and pips. | `generate-icons.py`; review for hand-written glyphs in `icons/extra.tsx` | Filled icons read as a different family and stop inheriting the theme. |
| DC-brand-08 | Below 16 px, use a label — not a pictogram. | review only | An unreadable smudge the user has to hover to identify. |
| DC-brand-09 | Illustrations use **exactly three colours**: `primary-100` fill, `primary-500` stroke, `accent-500` for the single point of attention. | `generate-illustrations.py` **raises** on a fourth | Drawings stop following the theme; the accent stops being a point of attention. |
| DC-brand-10 | Illustrations carry `data-decorative`. | review + `themes.spec.ts` | Calm mode leaves the decoration in place, which is the one thing it exists to remove. |
| DC-brand-11 | **No mascot.** A deliberate decision, not an omission. | review only | — |

---

## 2 · Colour — `DC-colour-*`

Source: `DESIGN.md` §1, §2, §8.

| # | Constraint | Enforced in | Failure symptom |
|---|---|---|---|
| DC-colour-01 | **No colour literal** outside `tokens.css` and `print.css`. Everything else reads `var(--c-*)`. | Stylelint `color-no-hex` / `color-named` / no `rgb()`; CI greps TS for literals | A colour that does not move when the theme does. |
| DC-colour-02 | The **complete** light palette is declared on bare `:root`. Later blocks may only *redefine* names, never introduce one. | `check-tokens.mjs` | A token defined only in a dark block renders as an empty `var()` — silent, no error, invisible element — for every user on the default setting. |
| DC-colour-03 | The two dark blocks (media-query and explicit) declare the same palette. | `check-tokens.mjs` | Choosing "dark" gives a different palette from having it chosen for you. |
| DC-colour-04 | The Tailwind bridge uses `@theme inline`. | `check-tokens.mjs` | Without `inline`, values freeze at build time and live theme switching repaints nothing. |
| DC-colour-05 | **Violet is ink, not a brand colour.** It marks action; it is never decorative. | review only | Violet everywhere means violet nowhere, and the eye stops finding the action. |
| DC-colour-06 | **The mandarin accent (`--c-accent-*`) means exactly one thing: AI-generated content.** Only `AiBadge` and components explicitly marking generated content may use it. | **partly the type system** — `CardTint` and `StatusVariant` exclude `accent`, so `Chip`/`Card` cannot express it; `AiBadge` reaches the recipe by setting `data-variant` directly. Raw `.ard-*` markup and `Button`'s `accent` variant are review only | It appears on a "new" badge or a CTA, stops meaning anything, and the teacher loses the one signal telling them which items need a second look. |
| DC-colour-07 | **Never pure black.** Text is `--c-ink-900` (`#1B1735`). Pure black exists only under `data-contrast="high"` and in print. | Stylelint (via DC-colour-01) + review | A page that reads as harsh and generic; the violet-black is what makes it feel like ink. |
| DC-colour-08 | **Never colour alone.** Every state band carries colour **and** a text label **and** a differing tint density. On paper, also a distinct underline style. | review only | The photocopier is black and white, and roughly one boy in twelve is colour-blind. Both lose the state entirely. |
| DC-colour-09 | The mastery band opacities are **computed**, and every glyph colour sits at a constant luminance of **0.46**. Do not re-derive them by eye. | review only | The ramp stops being monotonic in greyscale — the photocopied sheet no longer shows an order at all. That calibration is the whole point. |
| DC-colour-10 | `--c-mastery-ok` is **`#86CF5B`**, a yellow-green — *not* the info blue that deriving from the state families would suggest. | review only | The ramp green → yellow-green → amber → red → grey stops being ordered without colour. |
| DC-colour-11 | Footer tokens (`--c-foot-*`) do **not** invert between themes; the footer stays slate in both. | review only | The footer flips and the page loses its base. |

---

## 3 · Typography — `DC-type-*`

Source: `DESIGN.md` §3.

| # | Constraint | Enforced in | Failure symptom |
|---|---|---|---|
| DC-type-01 | **Student-facing text never goes below `body-l` (1.125 rem).** A product constraint, not a preference. | review only | A printed sheet a child at the back of the room cannot read. |
| DC-type-02 | **Caveat (`--font-hand`) appears at most once per page.** | review only | Twice on a page and it is a typeface instead of a gesture — the chalk stops being an accent. |
| DC-type-03 | Button labels are **Fredoka**, never Nunito. | `.ard-btn` in `recipes.css` + review | Buttons stop reading as one family. |
| DC-type-04 | Extracted or transcribed data is set in **mono**. | review only | The teacher cannot tell at a glance what a model transcribed from what a person wrote — and transcription is exactly what they are there to audit. |
| DC-type-05 | Fonts are self-hosted (`@fontsource-variable`). **No font CDN.** | review only | A third-party request on every page load, and a fallback flash when it fails. |
| DC-type-06 | `tabular-nums` on `table, .tabular, [data-numeric]`; `text-wrap: balance` on `h1..h4`. | `base.css` | Numbers that jitter column-to-column in a matrix the teacher scans vertically. |

---

## 4 · Shape, space, elevation — `DC-shape-*`

Source: `DESIGN.md` §4, §6.

| # | Constraint | Enforced in | Failure symptom |
|---|---|---|---|
| DC-shape-01 | **Card and Panel are different objects, not two sizes of one.** Card = radius `lg` + solid edge + shadow (a separate object). Panel = radius `md` + border, no shadow (a subdivision of the object you are already in). | `recipes.css` + review | Shadows everywhere flatten the hierarchy into noise, and nothing reads as contained by anything. |
| DC-shape-02 | Radius **roles** are fixed: `sm 10` focus ring · `md 16` buttons, panels, fields · `lg 24` cards · `xl 32` sheets, modals · `pill 999` chips, badges, gauges. | review only | Radius stops carrying meaning and becomes decoration. |
| DC-shape-03 | **Elevation is a solid edge, not a blur alone** — `0 4px 0 0 var(--edge)`. Buttons have physical thickness and are pressed down onto their edge. | `recipes.css` + review | The one piece of behaviour the whole system borrows from Duolingo disappears. |
| DC-shape-04 | Fields carry a **2 px** border, not 1 — the field must read as sunken. | `recipes.css` + review | Inputs read as flat labels and stop inviting a click. |
| DC-shape-05 | Spacing comes from the base-4 scale (2, 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96). | review only | Rhythm drifts a pixel at a time until nothing aligns. |

---

## 5 · Accessibility & state — `DC-a11y-*`

Source: `DESIGN.md` §5, §6, §8; `CLAUDE.md` conventions.

| # | Constraint | Enforced in | Failure symptom |
|---|---|---|---|
| DC-a11y-01 | Touch targets **≥ 44 px**. The button's minimum height is the touch target — non-negotiable. | `recipes.css` + `responsive.spec.ts` | The product is used on a phone in the classroom; a teacher standing between desks cannot hit it. |
| DC-a11y-02 | Three theme states, handled in order: complete light on bare `:root`; dark under `@media` guarded by `:not([data-theme='light'])`; explicit `[data-theme='dark']`. High contrast is an independent **layer** over either. | `check-tokens.mjs` + `themes.spec.ts` | An explicit "light" choice loses to a dark system preference, or high contrast is unreachable from dark. |
| DC-a11y-03 | `prefers-reduced-motion` and `[data-motion="off"]` cut all motion — **except `[data-timer]`**. | `motion.css` + review | A countdown frozen at 0 ms tells the user the window has already closed. A timer the user watches carries information. |
| DC-a11y-04 | `[data-calm="on"]` hides everything marked `[data-decorative]`. | review + `themes.spec.ts` | Reading mode does not actually reduce anything. |
| DC-a11y-05 | Keyboard focus is always visible (`--focus-ring`). | `base.css` + review | A keyboard user cannot tell where they are. |
| DC-a11y-06 | An invalid field changes its **border and** adds a message — never colour alone. | review only | See DC-colour-08; a colour-blind teacher sees a form that simply refuses to submit. |
| DC-a11y-07 | **Every screen ships empty, loading (with a `shape`) and error states.** `LoadingState` draws the shape of the page that is coming. | review only | A lone spinner says nothing about what is arriving, and an empty screen is indistinguishable from a broken one. |
| DC-a11y-08 | Mobile-first. The product is used on a phone in the classroom and a laptop at a desk; both are tested. | `responsive.spec.ts` | Half the actual usage is a horizontal-scroll experience. |

---

## 6 · Print & scan geometry — `DC-print-*`

Source: `DESIGN.md` §9; `apps/api/alppy/sheets/layout.py`. **Paper is the deliverable,
not a fallback** — sheets are photocopied and corrected on Sunday evening.

| # | Constraint | Enforced in | Failure symptom |
|---|---|---|---|
| DC-print-01 | A4 portrait, 14 mm margins. | `print.css` + `geometry.css.j2` | Content clipped by the printer's own margin. |
| DC-print-02 | Every printed label carries a colour **and** a distinct underline (solid, dashed, dotted, double, wavy), and both appear in the legend. | review only | The photocopy loses the distinction entirely. |
| DC-print-03 | Rules at 0.5 pt minimum. No colour fill as the sole distinction between two columns. | review only | A hairline that vanishes on the second-generation photocopy. |
| DC-print-04 | **One `.print-page` = one physical page**, never "one student's copy". | review only | An overflowing copy produces a sheet with no header and no code, belonging to nobody. |
| DC-print-05 | Corner fiducials are **real borders** (`[data-fiducial]`), so they survive the browser's "no background graphics" default. | `print.css` + `test_sheet_output.py` | Every sheet printed from a default browser is unscannable. |
| DC-print-06 | Always two sheets: the blank and the answer key. | `render.py` + review | — |
| DC-print-07 | `layout.py` and `print.css` describe the **same geometry**, and the detector reads it. Changing a number is a **layout version bump**, not a tweak. | `export-layout.py` diffed in CI; `Sheet.layout_version` | Old scans stop registering against the layout they were printed with — a term of paper becomes ungradeable. |
| DC-print-08 | The server-side PDF renderer consumes the **same** `print.css` and the same markup as the browser preview. | shared template + `test_sheet_output.py` | What the teacher previews is not what is printed. |
| DC-print-09 | An answer box is cropped **where it printed** (`AnswerBoxPlacement`, measured in Chromium), never recomputed from the current `SheetItem`. | `open_answer_grading.py` + review | An edit made after printing moves what the scanner crops, and the grader reads the wrong ink. |
| DC-print-10 | **A crop never leaves the statement region.** `measure_answer_boxes` refuses a box outside `ITEMS_TOP_MM..ITEMS_BOTTOM_MM`. | `render.py` **raises** (`SheetRenderError`) | The PII gate reads text only; what keeps a student's name out of an image sent to a provider is geometry. |

---

## 7 · Content, language, generation — `DC-content-*`

Source: `CLAUDE.md`; `DESIGN.md` §1; [`docs/privacy.md`](../privacy.md).

| # | Constraint | Enforced in | Failure symptom |
|---|---|---|---|
| DC-content-01 | No string literals in components. Three catalogues (`fr` default, `de`, `en`) stay in sync. | `check-i18n.mjs` (CI fails on a key missing from any locale) | A French teacher meets an English string mid-task. |
| DC-content-02 | Exercise content follows the language of the **source material**, never the UI locale. | review only | A German textbook exercise is silently presented as French. |
| DC-content-03 | Layouts survive German — the longest of the three locales. | `locales.spec.ts` | Buttons that fit in French and overflow in German. |
| DC-content-04 | AI-generated content is **marked** with the accent, and only generated content is. | review only | See DC-colour-06 — this is its enforcement in the UI. |
| DC-content-05 | AI-generated exercises are never printed without teacher approval (`Exercise.approved_at`). | `sheet_service` + tests | A model's mistake reaches thirty children with the school's name on it. |

**Adjacent invariants, enforced elsewhere.** The rules governing grading, mastery, and
what reaches a model provider are *not* design constraints and are not restated here:
see **Rules that lint cannot catch** in [`CLAUDE.md`](../../CLAUDE.md) and
[`docs/privacy.md`](../privacy.md). The two that touch pixels — DC-print-09 and
DC-print-10 — appear above because their enforcement is geometry.

---

## Pre-ship checklist

Before shipping a screen. Short on purpose — every line is something that has actually
gone wrong, or would be invisible until paper or a photocopier found it.

**Looks right**
- [ ] No colour literal — `pnpm exec stylelint` passes (DC-colour-01)
- [ ] Card vs Panel used deliberately; no shadow on a subdivision (DC-shape-01)
- [ ] Caveat appears at most once (DC-type-02); the accent only on generated content (DC-colour-06)

**Works for everyone**
- [ ] The three theme states, and high contrast over each (DC-a11y-02)
- [ ] `data-motion="off"` and `data-calm="on"` both do something (DC-a11y-03, -04)
- [ ] Touch targets ≥ 44 px on a real phone width (DC-a11y-01)
- [ ] **Screenshot it, desaturate it.** Is every state still distinguishable? (DC-colour-08)
- [ ] Empty, loading-with-a-`shape`, and error all exist (DC-a11y-07)

**Words**
- [ ] `pnpm i18n:check` passes; the German is checked for overflow (DC-content-01, -03)

**If it touches paper**
- [ ] Print it, photocopy it *twice*, and read it (DC-print-02, -03)
- [ ] Student-facing text is at or above `body-l` (DC-type-01)
- [ ] Fiducials print with background graphics **off** (DC-print-05)
- [ ] If a geometry number moved: layout version bumped, `export-layout.py` diff reviewed, old scans still register (DC-print-07)

---

## Changing a constraint

A constraint is not permanent — it is *load-bearing*, which means it is removed
deliberately or not at all. To change one:

1. **Find who leans on it.** `rg 'DC-colour-06'` across the repo, and read `DESIGN.md`
   for the spec it protects.
2. **Write the symptom you are accepting.** The failure-symptom column is the cost of
   the change. If you cannot name what gets worse, you have not finished thinking.
3. **Record a `Dn`** in [`decisions-log.md`](../decisions-log.md), in the existing
   format: what was decided, why, what it costs, and what would make us revisit it.
4. **Update this table** — the rule, its enforcement, and its symptom — and cite the
   new `Dn`.
5. **Move the enforcement with it.** A constraint that changes while its CI check does
   not is a constraint that now lies.

Adding one is the same, minus step 1. A rule earns a `DC` number when it is
load-bearing and has a nameable failure symptom; otherwise it is a spec, and it belongs
in `DESIGN.md`.
