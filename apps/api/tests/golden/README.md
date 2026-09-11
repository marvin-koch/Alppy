# The recognition golden set

What this measures: **whether the vision grader still reads a written answer the
way it did last week.** Nothing else in the repo does. `PROMPT_VERSION` moved
v2 → v3 with no measurement of the effect on a real model — the existing prompt
test proves v2 and v3 agree on a *fake* provider, which is a statement about the
routing, not about the reading (T9, T12).

## What is here

```
manifest.json     every sample: crop, expected transcription, expected verdict,
                  case label, and where the crop came from
crops/            the images, one per sample
baseline.json     the last accepted result, and the margin a run may fall by
```

The harness is `scripts/run-golden-set.py`. It sends each crop through the same
prompt the product sends (`load_prompt(PROMPT_NAME, PROMPT_VERSION)`) and
reports a confusion matrix over `{correct, wrong, blank, not_gradeable}` plus a
transcription exact-match rate.

## The corpus is seeded, not finished

Every sample currently in `crops/` is **rendered from a handwriting font**, and
the manifest says so in each `provenance` field. That is deliberate and it is
the weaker half of the deal: a font is regular in ways a child's hand is not, so
these samples exercise the harness, the prompt plumbing and the gate — they do
not tell you much about recognition accuracy.

The decision on where real samples come from (Q3 of audit 06) was: **build the
harness now, seed it with adult volunteers imitating pupil handwriting, and
revisit real pupil crops alongside a pilot** rather than speculatively. Adult
volunteers carry no privacy exposure and the audit puts them at roughly 70 % of
the value of the real thing.

So the next step is not code. It is:

1. Ask 3–5 adults to write the answers in `manifest.json` on paper, in pencil
   and in pen, including the messy ones — a crossed-out first attempt, an answer
   that runs outside the box, a number that could be a 1 or a 7.
2. Photograph or scan them, crop to the answer box.
3. Replace the corresponding `crops/*.png`, set `provenance` to
   `adult-volunteer`, and re-baseline.

Real pupil crops are a different conversation: nLPD, written parental consent,
and a geometric guarantee that no name is in the frame (`measure_answer_boxes`
already refuses a box outside `ITEMS_TOP_MM..ITEMS_BOTTOM_MM`, which is what
makes that guarantee structural rather than a promise). Do not add one without
that conversation having happened.

## Why sample 01 is the prompt injection

`prompt-injection-instruction` is first on purpose. The existing test proves the
defence *routes* correctly once triggered — an `instruction_like: true` flag
forces low confidence whatever the model reported — but the provider in that
test is a fake, so nothing anywhere says a real model raises the flag when shown
real instruction-shaped writing. This is the only sample whose rendered-font
provenance is arguably fine: what makes it an injection is the content, and a
pupil copying a printed instruction produces much the same thing.

## Running it

```bash
# Against whatever provider is configured. With the offline "echo" provider this
# exercises the plumbing and reports a floor, not an accuracy.
PYTHONPATH=apps/api python scripts/run-golden-set.py

# Re-accept the current numbers as the baseline, after reading them.
PYTHONPATH=apps/api python scripts/run-golden-set.py --update-baseline
```

CI runs it nightly and on any change under `alppy/ai/prompts/`, not on every
push: it is the one gate in the suite that necessarily talks to a real provider,
and putting a billed network call in front of every commit is how a gate gets
turned off.
