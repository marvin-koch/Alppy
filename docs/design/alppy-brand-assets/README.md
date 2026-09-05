# Alppy — bibliothèque d'identité

Design direction: **Craie Alpine** (see `Craie-Alpine-philosophie.md`).
Full manual: **`Alppy-identite-visuelle.pdf`** — 8 plates, A3 landscape.

Everything here is drawn in vector, from geometry, with no traced images, no icon
library and no licensed artwork. Fonts are referenced by name only; install them
with `@fontsource-variable/{fredoka,nunito,jetbrains-mono,caveat}`.

---

## The mark — "Le sourire"

Two slopes meeting at a summit, with a smile in the valley between them. The crossbar
of the **A** is the smile: one move, no added element, nothing that needs explaining.
It reads as a letter, as two peaks, and as a face turned friendly — growth, the Alps
and happiness carried by the same two strokes.

The mark carries **no accent colour**. The mandarin stays functional inside the product,
where it means AI-generated content; putting it in the logo would spend it on decoration.

Geometry lives on a 64-unit grid: slate inset 3u, radius 17u; stroke 6.2u with round
caps; feet at 16.2u and 47.8u on a 46.8u baseline; apex at 16.8u, so the slopes meet
the vertical at 27.8°. The smile is a quadratic curve, chord 18.8u at height 35.2u,
with a 5u rise. Its ends sit on the axis of the slopes, so the three strokes read as
one continuous drawing.

| File | Use |
|---|---|
| `logo/alppy-mark-primary.svg` | default — violet slate, white chalk, mandarin summit |
| `logo/alppy-mark-ink.svg` | on light backgrounds where violet would compete |
| `logo/alppy-mark-tint.svg` | inside violet-tinted surfaces |
| `logo/alppy-mark-mono-ink.svg` / `-mono-white.svg` | one-colour reproduction |
| `logo/alppy-mark-knockout.svg` | no plate — for use inside an existing container |
| `logo/alppy-mark-small.svg` | **below 24 px** — smile lifts to 34.0u and opens |
| `logo/alppy-logo-horizontal*.svg` | primary lockup (+ `-onink`, `-mono`) |
| `logo/alppy-logo-vertical.svg` | stacked lockup for square spaces |
| `logo/alppy-app-icon.svg` | 512 px app icon, flat, no gradient |
| `logo/alppy-favicon.svg` | 32 px, enlarged dot |

**Lockup rules.** Wordmark cap height = 0.62 of the mark height, aligned on the cap
band, not the bounding box (the descenders in *pp* and *y* make naive centring wrong).
Clear space = 1/4 of the mark height on all four sides.

**Never** stretch, recolour, rotate, or add a shadow to the mark — and never add the
mandarin accent to it. See Plate I.

## Pictograms — `icons/` (48)

24 px grid, 20×20 safe area, stroke 2.2 (never 2, never 3), round caps and joins,
`currentColor` only. Solid fills are reserved for dots and pips — a pictogram stays a
line drawing. Below 16 px, use a label instead.

## Illustrations — `illustrations/` (7)

120 px, flat, exactly three colours: `primary-100` fill, `primary-500` stroke,
`accent-500` for the single point of attention. All carry `data-decorative`, so
calm mode removes them. No mascot — that is a deliberate decision, not an omission.

## Mastery scale — `mastery/` + `alppy-mastery-tokens.css`

Five ordered bands carrying three independent signals plus a written label:

| Band | Threshold | Glyph |
|---|---|---|
| Acquis / Gefestigt / Solid | ≥ 0.90 | disc 4/4 |
| À revoir / Bald fällig / To review | 0.75 – 0.90 | disc 3/4 |
| Fragile / Unsicher / Fragile | 0.60 – 0.75 | disc 2/4 |
| S'efface / Verblasst / Fading | < 0.60 | disc 1/4 |
| Pas encore vu / Noch nicht / Not seen | never assessed | dashed ring |

The background opacities in the token file are **computed, not chosen**: each one
lands the blended luminance on a target so the ramp stays strictly monotonic in
greyscale. Every glyph is darkened to a constant luminance of 0.46 so all five states
have equal contrast. Plate V shows the desaturated proof — the sheets get photocopied,
so that is the test that matters.

Never use these colours alone.

## Colour and type

The 31 named tokens and the 10-step type scale are set out in Plates II and III.
Two rules that lint cannot catch: the mandarin accent belongs to AI-generated content
and nothing else, and Caveat appears at most once per surface.
