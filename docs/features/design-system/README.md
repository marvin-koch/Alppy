# Design System

**Status:** describes `main` as of 2026-09-09
**Audience:** developers, LLM agents, reviewers
**Authorities:** the shipped assets in `docs/design/`, then [`DESIGN.md`](../../../DESIGN.md)

---

## 1 · What it does

"Craie Alpine" is Alppy's identity, and it is **shipped, not described**.
`docs/design/` holds the manual (8 A3 plates), the philosophy note, and
`alppy-brand-assets/brand/` with `logo/` (26 files), `icons/` (48 pictograms),
`illustrations/` (7), `mastery/` (5 band glyphs) and `alppy-mastery-tokens.css`.

`packages/ui/src/design/` turns that into five stylesheets the whole product reads —
including the printed sheet, which inlines them at render time rather than copying
them. So a token change reaches the paper.

```
  docs/design/alppy-brand-assets/       ← the identity. Import it; never redraw it.
        │  logo/ icons/ illustrations/ mastery/ alppy-mastery-tokens.css
        ▼
  packages/ui/src/design/
     tokens.css     every colour, size, radius, shadow — the ONLY colour literals
     base.css       resets, typography scale, focus
     recipes.css    .ard-btn · .ard-card · .ard-panel · .ard-input
     motion.css     four durations, two curves, reduced-motion
     print.css      paper. Overwrites tokens rather than bypassing them.
        │
        ├──▶ apps/web              the teacher UI
        └──▶ alppy/sheets/html.py  read from disk at render time → the PDF
```

### Key properties

1. **Where the shipped assets disagree with prose anywhere in the repo — including
   `DESIGN.md` — the assets win.**
2. **Two files may contain colour literals**, `tokens.css` and `print.css`, and CI
   fails on any other. Print is exempt because it *overwrites* tokens rather than
   bypassing them.
3. **Paper is not a fallback.** The printed sheet is a first-class output of the same
   system, and it is photocopied in black and white.

---

## 2 · Invariants (load-bearing)

| # | Invariant | Enforced in | Why it matters | Failure symptom |
|---|---|---|---|---|
| I-design-01 | **The mandarin accent (`--c-accent-*`) means exactly one thing: AI-generated content.** Only `AiBadge` and components explicitly marking generated content may use it. | review | It is the teacher's one signal for "read this before printing it" | The accent stops meaning anything; unreviewed AI blends in |
| I-design-02 | **Caveat (`--font-hand`) appears at most once per page.** | review | It is the chalk — a gesture, not a typeface | Twice on a page and it is just another font |
| I-design-03 | **Card and Panel are different objects.** Card: radius `lg`, solid edge, shadow — a separate object. Panel: radius `md`, border, no shadow — a subdivision of the object you are in. | `recipes.css` | Shadows everywhere flattens hierarchy into noise | The page reads as a pile of equal boxes |
| I-design-04 | **Never colour alone.** Every state band carries colour **and** a text label **and** a differing tint density; on paper also a distinct underline and glyph. | `tokens.css`, `MasteryCell`, `print.css` | The photocopier is black and white, and ~1 boy in 12 is colour-blind | A band becomes invisible to a reader or a photocopy |
| I-design-11 | **The mastery ramp encodes mastery only.** A score, a percentage or a points total never borrows `--c-mastery-*`; `PointsCell` is neutral-faced and states its number. | `PointsCell.tsx`, D49 | The five bands are calibrated for decayed competency evidence, not for one morning's paper | "71 %" silently asserts a band nobody computed |
| I-design-12 | **A wait is indicated in proportion to its length, and honestly about what is known.** Skeleton for a page; `Spinner` for an indeterminate wait; `ProgressRing` only where a real fraction exists. | `Spinner.tsx`, `scans/new/page.tsx`, `scans/[scanId]/page.tsx`, D54 | A meter drawn at 0 for an unmeasured task claims no progress has been made | A teacher closes the tab mid-upload because nothing looked alive |
| I-design-13 | **A disabled control keeps its variant's nature, and a refusal always has somewhere to render.** Ghost stays face-less and drop-less when disabled — ink alone carries the state; and a dialog shows its `error` whether or not it asked for a typed confirmation. | `recipes.css` (`.ard-btn[data-variant='ghost']:disabled`), `ConfirmDestructive.tsx`, D80 | The shared `:disabled` face is right for a button that HAS a face; on an edge-less one it invents a box. And a message the server already sent must never depend on which optional field is present | An out-of-moves arrow reads as broken, or a refusal the API explained goes silently missing |
| I-design-05 | **`--c-mastery-*` is calibrated, not chosen.** `ok` is `#86CF5B`; every band's `-glyph` sits at luminance 0.46 with a *computed* background opacity, so the ramp stays monotonic in greyscale. | `tokens.css`, `docs/design/alppy-mastery-tokens.css` | The sheets get photocopied | The bands stop being ordered once printed |
| I-design-06 | **Violet is ink, not a brand colour.** It marks action, never decoration. | review | A product where everything is violet marks nothing | The primary colour stops meaning "you can do this" |
| I-design-07 | **Never pure black.** Text is `--c-ink-900` (`#1B1735`). Pure black exists only in high contrast and in print. | `tokens.css` | The palette has a temperature; black breaks it | Text reads harsh and off-brand |
| I-design-08 | **Student-facing text never goes below `body-l` (1.125 rem).** The textbook crop is exempt: it reproduces the book at 1:1. | `print.css`, `DESIGN.md` §3 | A product constraint, not a preference | Unreadable paper in a real classroom |
| I-design-09 | **No colour literal outside `tokens.css` and `print.css`; no icon library; no font CDN.** | CI | The library is drawn in-repo and self-hosted | Drift from the identity, and a third-party runtime dependency on paper |
| I-design-10 | **Every screen ships empty, loading (with a `shape`) and error states.** Touch targets ≥ 44 px. | review, `LoadingState` | The product is used on a phone in a classroom | A spinner that says nothing about what is coming |

The logo, for the record: **"Le sourire"** — two slopes meeting at a summit with a
smile in the valley, forming an **A**, on a violet rounded slate. Not a slate crossed
by a chalk stroke, and **it carries no mandarin accent** — the accent is functional
inside the product, and spending it on decoration would cost I-design-01.
Pictogram stroke is **2.2 — never 2, never 3**.

---

## 3 · Module map

| Path | Owns | Depends on |
|---|---|---|
| `docs/design/alppy-brand-assets/brand/` | The identity: logo, 48 pictograms, 7 illustrations, 5 band glyphs, the mastery tokens | — |
| `packages/ui/src/design/tokens.css` | Every colour, radius, shadow, duration. **Colour literals live here** | the brand assets |
| `packages/ui/src/design/base.css` | Reset, the type scale, focus | tokens |
| `packages/ui/src/design/recipes.css` | `.ard-btn`, `.ard-card`, `.ard-panel`, `.ard-input` | tokens |
| `packages/ui/src/design/motion.css` | Four durations, two curves, `prefers-reduced-motion` | — |
| `packages/ui/src/design/print.css` | Paper: page geometry, band underlines, the `body-l` floor. The second file allowed colour literals | tokens |
| `packages/ui/src/icons/` | The pictograms as components — `currentColor` only | brand icons |
| `alppy/sheets/html.py::read_design_css` | Reads `{tokens,base,print}.css` **from disk at render time**; raises `DesignSystemNotFoundError` rather than rendering unstyled | the four files above |
| `apps/web/messages/{fr,de,en}.json` | The three catalogues; `pnpm i18n:check` fails on a key missing from any | — |

---

## 4 · How to extend this feature

1. **Look in `docs/design/` first.** If the thing you are about to draw is already
   shipped, import it. That is I-design-09 and the first line of `CLAUDE.md`.
2. **New colour?** It goes in `tokens.css`, or it does not exist.
3. **New state?** It needs a colour *and* a label *and* a tint density *and* a print
   treatment before it ships (I-design-04).
4. **Touching print?** Remember that `print.css` and `layout.py` describe the same
   geometry and the detector reads it — see `sheets/` I-sheets-03.

### LLM checklist

- [ ] Read §2 — these are not suggestions
- [ ] Is `--c-accent-*` about to mark something that is not AI-generated? (I-design-01)
- [ ] Is this a card or a panel? Did you add a shadow to a subdivision? (I-design-03)
- [ ] Does any new state rely on colour alone? (I-design-04)
- [ ] Any hex outside `tokens.css` / `print.css`? (CI will fail — I-design-09)
- [ ] Does the screen have empty, loading-with-shape and error states? (I-design-10)
- [ ] Any string literal in a component instead of a message key?

---

## 5 · Privacy & safety

| Concern | Where it is handled | Why |
|---|---|---|
| Accessibility | Three theme states (light, dark, system), high contrast, reduced motion, `calm` | The teacher's own setting, stored on `Teacher` |
| Colour-blindness | I-design-04, I-design-05 | ~1 boy in 12; the matrix is the most colour-dense screen in the product |
| The photocopier | The luminance-0.46 glyph ramp and computed opacities | Sheets are copied before they reach students |
| Font privacy | `@fontsource-variable`, self-hosted; no CDN | No third-party request from a school's browser |

---

## 6 · Testing strategy

The design system is checked by CI gates and by screenshots rather than by unit tests:

| Invariant | Checked by |
|---|---|
| I-design-04, I-design-05, I-design-08 | Playwright screenshots at every theme × locale, at 390×844 and 1440×900 (`pnpm test:e2e`) |
| I-design-08 | `apps/api/tests/test_sheet_output.py` — the printed document is asserted, not eyeballed |
| I-design-09 | The colour-literal lint (CI fails on a hex outside the two exempt files) |
| I-design-13 | `e2e/teaching.spec.ts` — asserts the disabled ghost arrow is transparent, and that the refusal's count is on screen |
| i18n | `pnpm i18n:check` — fails on a key missing from any of `fr`, `de`, `en` |
| I-design-01, 02, 03, 06, 07, 10 | **Review.** These are the ones lint cannot catch, and the reason `CLAUDE.md` states them |

```bash
pnpm lint && pnpm typecheck && pnpm i18n:check && pnpm test:e2e
```

---

## Companion documents

- [`architecture.md`](architecture.md) — how the five stylesheets compose, and how the paper reads them
- [`decisions.md`](decisions.md) — D14, D15, D19, D16, D25
- [`../../../DESIGN.md`](../../../DESIGN.md) — the full system, section by section
- [`../sheets/`](../sheets/) — the consumer with the strictest requirements

**Last updated:** 2026-09-09
