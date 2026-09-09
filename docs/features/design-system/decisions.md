# Design System Decisions Log

D-numbers follow the repo-wide [`docs/decisions-log.md`](../../decisions-log.md).

---

## D19 · The shipped brand library outranks the written brief

**Date:** 2026-09 · **Affected invariants:** I-design-01, I-design-05, I-design-09

**Background.** `docs/design/` — the "Craie Alpine" manual plus `alppy-brand-assets/` —
arrived *after* the first UI was built, and contradicts the brief in three places.

**Chosen.** The assets win, and the prose was corrected rather than the assets adapted:

1. **The mark is "Le sourire"** — two slopes meeting at a summit with a smile in the
   valley, forming an **A** — not a slate crossed by a chalk stroke.
2. **The mark carries no mandarin accent.** The brief asked for a mandarin dot; the
   library forbids it, correctly. The accent is functional inside the product (it
   means AI-generated content), and putting it in the logo spends it on decoration.
   This is the stronger reading of the brief's own rule.
3. **`--c-mastery-ok` is `#86CF5B`**, a yellow-green — not the info blue that deriving
   the band scale from the state families produced (superseding D15).

**Also settled:** pictogram stroke is **2.2** exactly. Band glyphs are disc 4/4 · 3/4 ·
2/4 · 1/4 · a dashed ring — a coarse quarter-turn per band, because that survives a
photocopy and a 12 px rendering where a subtle density ramp does not.

**Icons and illustrations are generated**, by
`packages/ui/scripts/generate-{icons,illustrations}.py`, rather than transcribed by
hand — so refreshing the brand is a re-run, not a design exercise. The illustration
generator maps the flat export hexes back onto tokens (so the drawings follow the
theme) and **fails** if an asset introduces a fourth colour.

**Tradeoff**
- ✅ One identity, in one place, with no hand-copied second version to drift
- ✅ The greyscale ramp is calibrated rather than eyeballed
- ❌ Some earlier UI had to be redone

**How it reinforces I-design-09:** "Import those files. Do not redraw them."

---

## D14 · State families derive `-100` and `-600`; the spec fixed only `-500`

**Date:** M0 · **Affected invariant:** I-design-07

Derived consistently for both themes and documented inline in `tokens.css`. In dark
mode the state `-600` step is *lighter* than `-500` so that text on the dark `-100`
tint passes AA — while `primary-600` and `accent-600` keep the darker button-edge role
the spec assigned them.

---

## D15 · `--c-mastery-*` maps onto the state families

**Date:** M0 · **Partly superseded by D19** · **Affected invariant:** I-design-05

solid→success, ok→info, weak→warn, fading→danger, none→ink-300: an ordered
green→blue→amber→red→grey scale. D19 replaced the `ok` step with the shipped
`#86CF5B`; the *ordering* principle survives, and the requirement that the ramp be
monotonic in greyscale is now met by calibration rather than by derivation.

---

## D16 · Responsive is a first-class requirement

**Date:** M0, at user request · **Affected invariant:** I-design-10

The teacher uses a laptop at a desk **and** a phone in the classroom — scanning copies
with the phone camera is an explicit workflow, not a nicety. Mobile-first, drawer nav
under `md`, the matrix scrolling in its own container with a sticky name column, and
screenshot tests at 390 px and 1440 px.

**Mobile is not a degraded desktop.** That sentence is the decision; the breakpoints
are the consequence.

---

## D25 · The web app is hosted on Cloudflare Workers; the API is not

**Date:** 2026-09 · **Affected invariant:** none directly

Recorded here because it constrains the front end: no Node-only APIs in the web
runtime, and the fonts must be self-hosted assets rather than a CDN request from a
school's browser. See [`docs/deploy-cloudflare.md`](../../deploy-cloudflare.md).

---

## The rules lint cannot catch

These have no D-number because they were never in doubt — they are stated in
`CLAUDE.md` for whoever writes the code, and in §2 here for whoever reviews it:

| Rule | Why it is a rule and not a preference |
|---|---|
| The accent means AI-generated content, and nothing else | It is the teacher's only signal for which items need a second look |
| Caveat at most once per page | Twice and it is a typeface, not a gesture |
| Card ≠ Panel | Shadows everywhere flattens the hierarchy into noise |
| Never colour alone | The photocopier is black and white; ~1 boy in 12 is colour-blind |
| Violet is ink | A product where everything is violet marks nothing |
| Never pure black | The palette has a temperature |
| Never below `body-l` for a student | A product constraint. Children read this on paper, in a classroom |

---

## When policy changes

```json
{
  "change": "use --c-accent-500 for the 'new' badge on the sources screen",
  "reason": "it draws the eye",
  "date": "YYYY-MM-DD",
  "decision": "rejected — violates I-design-01",
  "rationale": "the accent is spent the moment it means two things. Use
                --c-primary-100 with a label, like every other badge."
}
```
