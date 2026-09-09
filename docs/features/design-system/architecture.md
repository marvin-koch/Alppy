# Design System Architecture

## Component diagram

```
  docs/design/                                    ← the shipped identity
    Alppy-identite-visuelle.pdf (8 A3 plates) · philosophy note
    alppy-brand-assets/brand/
        logo/ (26)   icons/ (48)   illustrations/ (7)   mastery/ (5)
        alppy-mastery-tokens.css
            │
            │  packages/ui/scripts/generate-icons.py
            │  packages/ui/scripts/generate-illustrations.py   ← generated, not transcribed
            ▼
  packages/ui/src/
      design/tokens.css ──┬── base.css ── recipes.css ── motion.css
                          └── print.css        (the two files allowed colour literals)
      icons/  illustrations/  brand/  components/
            │
     ┌──────┴───────────────────────────────┐
     ▼                                      ▼
  apps/web (Next.js, Tailwind v4)     alppy/sheets/html.py
     the teacher UI                      read_design_css() at RENDER time
     three themes × three locales        │
                                         ▼
                                   the printed A4 page → PDF → photocopier
```

The right-hand branch is the unusual one. The PDF renderer does not embed a copy of
the design system; it **reads the files off disk** every time it renders, and raises
`DesignSystemNotFoundError` if they are missing. That is why the browser preview and
the paper cannot drift, and why a token change reaches a classroom.

## Data flow

### Tokens → everything

```css
/* tokens.css — the only place (with print.css) a hex may appear */
--c-ink-900: #1b1735;      /* never #000 (I-design-07) */
--c-primary-500: #5b3ff0;  /* violet: ink, marks action (I-design-06) */
--c-accent-500: #ff8a3d;   /* mandarin: AI-generated content, and nothing else (I-design-01) */

--c-mastery-solid: #00c48c;   --c-mastery-solid-glyph: #00996d;  --c-mastery-solid-bg-opacity: .536;
--c-mastery-ok:    #86cf5b;   --c-mastery-ok-glyph:    #56853a;  --c-mastery-ok-bg-opacity:    .567;
--c-mastery-weak:  #ffc93c;   --c-mastery-weak-glyph:  #947523;  --c-mastery-weak-bg-opacity:  .561;
--c-mastery-fading:#ff5a5f;   --c-mastery-fading-glyph:#ee5459;  --c-mastery-fading-bg-opacity:.154;
--c-mastery-none:  #a9a3c7;   --c-mastery-none-glyph:  #77738c;  --c-mastery-none-bg-opacity:  .116;
```

Read the three columns together: the glyph colours sit at a **constant luminance of
0.46** and the background opacities are *computed* from them, so the five bands stay
monotonically ordered when the sheet is photocopied. The numbers look arbitrary
because they are derived, not chosen. Do not adjust one by eye (I-design-05).

### The type scale

Four fonts, four roles, all self-hosted via `@fontsource-variable`:

| Font | Token | Role |
|---|---|---|
| Fredoka | `--font-display` | Titles, ring numerals, **all button labels** |
| Nunito | `--font-sans` | Everything else. Good French diacritics |
| JetBrains Mono | `--font-mono` | Code, and **transcribed data** — a transcription must look like data, because the teacher audits it |
| Caveat | `--font-hand` | The chalk. **At most once per page** (I-design-02) |

`body-l` (1.125 rem / 1.6) is the **floor for any text a student sees**. The one
exemption is the textbook crop, which reproduces the book at 1:1 (I-design-08, D40).

### The four recipes

`.ard-btn` · `.ard-card` · `.ard-panel` · `.ard-input`. Everything else composes with
utilities. The distinction that gets broken most often:

| | Card | Panel |
|---|---|---|
| Radius | `lg` (24px) | `md` (16px) |
| Edge | solid edge **+ shadow** | border, **no shadow** |
| Means | *a separate object* | *a subdivision of the object you are already in* |

## Component interaction

### Themes — three states, not two

An explicit choice stamps `data-theme`; the default "system" stamps nothing and
`prefers-color-scheme` decides. Plus `contrast`, `motion` and `calm`, all stored per
teacher and applied at the root. In dark mode the state `-600` step is *lighter* than
`-500` so text on the dark `-100` tint still passes AA — while `primary-600` and
`accent-600` keep their darker button-edge role (D14).

### Print — paper is not a fallback

`print.css` is the second file allowed colour literals because it **overwrites**
tokens rather than bypassing them: on paper, pure black is allowed, tints become
underline styles, and every band gets a distinct hatch. It shares the page geometry
with `alppy/sheets/layout.py` — and the detector reads that geometry, which makes any
number in it a layout version bump (`I-sheets-03`).

### Responsive

Mobile-first, base 360–430 px, breakpoints `sm 640 · md 768 · lg 1024 · xl 1280`.
Below `md` the class/subject rail becomes a drawer plus a bottom tab bar. The mastery
matrix scrolls horizontally **inside its own container** with a sticky name column —
the page body never scrolls sideways. Touch targets ≥ 44 px, which is already the
floor on `.ard-btn` and `.ard-input`.

## Edge cases

- **A fourth colour in an illustration.** → the generator **fails**. The illustrations
  map three flat export hexes back onto tokens so the drawings follow the theme; a
  fourth has no token to map to.
- **A missing design CSS file at render time.** → `DesignSystemNotFoundError`, not an
  unstyled sheet.
- **A locale missing a key.** → `pnpm i18n:check` fails CI. Three catalogues, `fr`
  default.
- **Exercise content in another language than the UI.** → correct, and required:
  exercise content follows the **source material**, never the UI locale. The printed
  true/false glyphs (V/F · R/F · T/F) follow the exercise's language, and the detector
  reads bubbles by position — so a mislabelled item prints the wrong letters next to
  the right holes.
- **A long French label in a narrow column.** → `text-wrap: balance` on `h1..h4`, and
  the layout is checked at 390 px in the screenshot suite, not assumed.

---

**Companion:** [`README.md`](README.md) §2 for the load-bearing rules.
