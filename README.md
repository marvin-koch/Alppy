# Alppy

**Teach more personally, more efficiently.** Alppy is a teacher-facing tool for
Swiss compulsory school — Sekundarstufe I / cycle 3, roughly ages 10 to 16.

It closes one loop:

1. **Build** an exercise sheet for tomorrow's lesson from your own textbooks, and
   print it.
2. **Scan** the completed copies back in — a phone photo is fine. Alppy
   identifies each student from the printed code, grades the multiple-choice and
   true/false items, and shows you what it read and how sure it is.
3. **See** a five-band mastery matrix per class, per student, per competency.
4. **Generate** a differentiated sheet for every student, targeted at their own
   gaps — retrieved from your textbooks first, topped up with AI-generated
   exercises that are clearly marked and never printed without your approval.

The printed A4 sheet is the deliverable, not a degraded version of a screen.

---

## Quickstart

```bash
git clone <this repo> && cd Alppy
cp .env.example .env
docker compose up
```

Then open <http://localhost:3000> and sign in as the demo teacher printed in the
compose logs. **No API key is required**: the AI layer ships deterministic
offline providers so the whole product runs on a clean machine.

Working on it without Docker:

```bash
corepack enable pnpm && pnpm install
pnpm dev                      # web + api (needs postgres, redis, minio running)

python3 -m venv .venv && .venv/bin/pip install -e "apps/api[dev]"
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests -q
```

---

## What is in the box

| Feature | Where |
|---|---|
| **F1** Exercise selection and sheet generation | `alppy/ingest`, `alppy/services/retrieval.py`, `alppy/sheets` |
| **F2** Scan, registration, detection, grading | `alppy/scan` |
| **F3** Mastery tracking, five-band matrix | `alppy/mastery`, `MasteryMatrix` |
| **F4** Adaptive per-student sheets | `alppy/services/adaptive_service.py` |
| **F7** Navigation and overview | `apps/web/app/[locale]` |

Three locales from day one — **French (default), German, English** — in light,
dark and high-contrast themes, on a phone and on a laptop.

---

## The parts worth looking at

**[`apps/api/alppy/sheets/layout.py`](apps/api/alppy/sheets/layout.py)** is the
single source of truth for the printed page. The print CSS, the PDF renderer and
the scan detector all read the same millimetres, which is why changing a number
there is a *layout version bump* rather than a tweak.

**The student code is 32 checksummed bits, not a QR code and not OCR.** OCR on a
phone photo of a photocopy is exactly where these systems fail. Every single- and
double-bit misread is rejected rather than decoding to a *different real
student* — a failed read asks the teacher, a wrong read files a child's answers
under someone else's name.

**The detector measures each bubble against a local ring of paper**, not a global
threshold. The synthetic degradation suite caught the alternative doing something
worse than failing: reading a light pencil mark as blank *with full confidence*,
silently scoring a child zero. When most of a page reads empty, Alppy now
distrusts its own blanks and sends them to you.

**[The mastery model](docs/mastery-model.md)** is two factors —
weighted recent accuracy × a recency term — and the second one is the whole
reason a "fading" band can actually fade. It is documented, tested against worked
examples, and deliberately simple enough to argue with.

**No student name ever reaches a model provider.** Prompts carry the UID
(`7B_15`). The gate in `alppy/ai/scrub.py` raises rather than redacting, because
a name in a prompt is a bug and must fail loudly. See
[`docs/privacy.md`](docs/privacy.md).

---

## Documentation

| Document | What it covers |
|---|---|
| [`DESIGN.md`](DESIGN.md) | "Encre violette" — the full visual identity |
| [`CLAUDE.md`](CLAUDE.md) | Conventions, and the design rules lint cannot catch |
| [`docs/plan.md`](docs/plan.md) | Milestones, domain model, API surface, screens |
| [`docs/architecture.md`](docs/architecture.md) | System diagram and the four data flows |
| [`docs/mastery-model.md`](docs/mastery-model.md) | The formula, the constants, the limits |
| [`docs/sheet-layout.md`](docs/sheet-layout.md) | Layout v1 geometry and versioning |
| [`docs/rag.md`](docs/rag.md) | Chunking, ranking, retrieve-then-generate |
| [`docs/privacy.md`](docs/privacy.md) | Swiss FADP, data residency, the PII gate |
| [`docs/deploy-cloudflare.md`](docs/deploy-cloudflare.md) | Free hosting for the web app, and why the API cannot join it |
| [`docs/curriculum.md`](docs/curriculum.md) | LP21 and PER in one model |
| [`docs/research/textbook-access-ch.md`](docs/research/textbook-access-ch.md) | Can Swiss textbooks be accessed programmatically? |
| [`docs/decisions-log.md`](docs/decisions-log.md) | Every call made without asking |
| [`docs/handover.md`](docs/handover.md) | What is built, what is stubbed, what is next |

---

## Licensing and content

Alppy indexes **textbooks the teacher already licitly possesses**, on their own
instance, and never redistributes them. The repository itself contains **no
copyrighted textbook content**: the demo corpus in `apps/api/alppy/seed/data` is
self-authored, and the demo roster contains no real student.

Whether a third-party SaaS may index Swiss publisher material is a genuinely open
legal question — [the research note](docs/research/textbook-access-ch.md)
separates what was verified against primary sources from what needs a Swiss
lawyer, and does not pretend to settle it.

---

## Status

MVP. See [`docs/handover.md`](docs/handover.md) for what is real, what is
stubbed, and the ten assumptions most worth challenging.
