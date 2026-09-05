# Curriculum model

Status: seed data for M1 (Corpus milestone). Covers mathematics, cycle 3 (Sek I / CO,
ages ~12–15), for both Swiss curricula in scope: **LP21** (Lehrplan 21, German-speaking
cantons) and **PER** (Plan d'études romand, Suisse romande). Data lives in
`apps/api/alppy/seed/data/*.json`; this document explains the model those files
implement and lists every code seeded, with its source.

## 1. Why one `Competency` table for two curricula

Alppy is used by teachers in both language regions. A French-speaking teacher in Sion
and a German-speaking teacher in Chur are teaching largely the same mathematics, but
each references it through their own official curriculum text. Rather than modelling
"LP21 competency" and "PER competency" as separate tables — which would force every
downstream feature (chapters, exercises, mastery) to branch on curriculum — Alppy uses
a single `Competency` table with a `curriculum` discriminator column. Everything that
references a competency (chapters, exercises, mastery snapshots) just holds a
competency id or code; it does not need to know which curriculum that competency
belongs to.

Fields on `Competency`:

- `curriculum` — `"LP21"` or `"PER"`. A simple enum, not a foreign key to a separate
  "Curriculum" table, because the two curricula never share rows — a competency is
  authored under exactly one.
- `code` — the official (or, where noted below, our own sub-division of the official)
  identifier, e.g. `MA.2.A.1` (LP21) or `MSN 33.2` (PER). Codes are unique within a
  curriculum but the two curricula are allowed to reuse surface syntax coincidentally;
  nothing assumes cross-curriculum code uniqueness.
- `parent_code` — `null` for a top-level area, otherwise the `code` of the parent
  competency in the same curriculum. This gives a two-level tree for this seed
  (area → competency); the schema does not limit depth, so a future, finer-grained
  seed (e.g. LP21 Kompetenzstufen `a`/`b`/`c`) can nest further without a migration.
- `subject`, `cycle` — `"mathematics"`, `3` for every row in this seed. Present so the
  same table serves other subjects and cycles later.
- `labels`, `description` — each an object with `de`/`fr`/`en` keys. All three locales
  are populated for every row, but they are **not equally authoritative**: see §2.

## 2. Anchor language vs. translation

The official wording of a curriculum is a legal and pedagogical reference; a
translation is a convenience for a teacher (or this document) working in another
locale. Alppy keeps that asymmetry visible rather than pretending all three locales are
equally "official":

- For every **LP21** competency, the **German** text is the anchor — written first,
  taken from or built directly on the cantonal Lehrplan 21 wording. French and English
  are translations produced for this seed and are not official CIIP/EDK text.
- For every **PER** competency, the **French** text is the anchor — taken from or built
  directly on the official CIIP wording (see §4 for exactly which parts are verbatim
  vs. reconstructed). German and English are translations produced for this seed.

A teacher viewing a competency in their own UI locale is always reading either the
anchor or a translation of it; the UI does not need to track which, but this document
and the `curriculum` column together make it recoverable (`curriculum=LP21` → anchor is
`labels.de`; `curriculum=PER` → anchor is `labels.fr`).

## 3. Chapters: teacher-facing, cross-curriculum, many-to-many

A `Chapter` (`key`, `subject`, `labels`, `competency_codes`) is the grouping a teacher
actually thinks in — "Fractions", "Pythagoras" — independent of curriculum. It is not a
node in the competency tree; it is a many-to-many join (`chapter_competency` in
`docs/plan.md`'s domain model) onto whichever competencies, from whichever curriculum,
a teacher (or, in this seed, we) judge that chapter to develop.

Concretely, the seeded chapter `plane_geometry_pythagoras` points at both
`MSN 31.2` (PER) and `MA.2.A.2` (LP21) — two codes from two different official
documents that happen to describe the same mathematical content. This is exactly the
point of the many-to-many design: a Suisse-romande teacher builds a sheet from this
chapter and reports progress against PER; a Deutschschweiz teacher builds a sheet from
the *same* chapter and reports progress against LP21. Neither has to know the other
curriculum exists.

Chapters are teacher-owned in the full product (a teacher can create their own
chapters and attach competencies of their choosing); this seed provides 7 built-in
chapters as the demo/starting corpus.

## 4. Exercises, and how mastery aggregates across curricula

Each `Exercise` carries `competency_codes` (a list — an exercise can address more than
one competency) and belongs to exactly one `chapter_key`. It also carries `language`
(`fr`/`de`) — the language of the source material it represents, **not** the teacher's
UI locale. That distinction matters operationally: a teacher who prefers the app in
German may still have uploaded (or, in this demo, be shown) a French textbook's
exercises verbatim in French, because grading and print rendering must preserve the
source language.

Mastery aggregates **per (student, competency)**, as documented fully in
`docs/mastery-model.md`. Concretely: every `Attempt` links a student, an exercise, and
(through the exercise) one or more competency codes. `MasterySnapshot` rows are
computed per competency code, so:

- An exercise tagged only `MSN 32.1` contributes to the student's PER mastery of
  "Nombres réels" and to nothing on the LP21 side.
- An exercise tagged only `MA.2.A.1` contributes to the student's LP21 mastery of
  "Flächeninhalt … berechnen" and to nothing on the PER side.
- An exercise tagged with **both** a PER and an LP21 code (this seed does not do this,
  to keep provenance clean per source document, but the schema allows it) would update
  both mastery rows from the same attempt.

The two curricula's mastery rows simply coexist in the same `MasterySnapshot` table,
distinguished by which competency (and therefore which `curriculum`) they point at. A
class or student mastery matrix (`GET /classes/{id}/mastery`) can filter or group by
`curriculum` for a teacher who only wants to see progress against their own official
reference, or show both side by side for a bilingual school.

## 5. What was verified against an official source, and what is approximate

Both official portals resist naive automated fetching: `lehrplan21.ch` and the
cantonal Lehrplan viewers (e.g. `zh.lehrplan.ch`, `v-fe.lehrplan.ch`) returned
HTTP 403 to direct fetches; `plandetudes.ch` redirects through a JavaScript-rendered
portal (`portail.ciip.ch`) that returns no static text to a non-browser fetch. Where
direct fetches failed, this seed relies on (a) cached search-engine text of those same
pages, and (b) one official PDF that *did* fetch cleanly and was extracted with
`pdftotext`: `PER_print_MSN_33.pdf`, published by CIIP (2010) at
`bdper.plandetudes.ch` — this is a genuine primary-source PDF, not a paraphrase — plus
a Fribourg cantonal planning document (`coveveyse.ch`, based explicitly on the PER)
that corroborates the MSN 31–35 titles. Every code below is marked accordingly.

**Verified** = the code and its official title/wording were read directly from an
official source (a Lehrplan 21 cantonal viewer's cached text, or the CIIP PDF).
**Approximate** = the code's *position in the numbering scheme* is consistent with the
confirmed pattern, but the specific competency wording attached to it here is our own
reconstruction in the style of the source, not a verbatim quote we were able to read.
The sub-codes we invented ourselves (LP21 `MA.x.y.n` competency numbers beyond what we
could confirm, and *all* PER `MSN 3x.n` sub-codes) are flagged explicitly — the PER
does not officially subdivide below `MSN 31`–`MSN 35` at cycle 3; that second level is
our own grouping of the official content into exercise-sized topics, done openly rather
than inventing fake CIIP numbering.

### LP21 (anchor language: German)

| Code | Official/approximate title (German anchor) | Status | Source |
|---|---|---|---|
| MA.1.A | Zahl und Variable — Operieren und Benennen | Verified (area/aspect combination and general competency content) | [zh.lehrplan.ch, cached](https://zh.lehrplan.ch/index.php?code=b%7C5%7C0%7C1%7C1) |
| MA.1.A.2 | Zahlen vergleichen, ordnen, runden und Ergebnisse überschlagen | Verified (content), code position approximate | zh.lehrplan.ch (cached search text) |
| MA.1.A.3 | Grundoperationen: addieren, subtrahieren, multiplizieren, dividieren, potenzieren | Verified — the code `MA.1.A.3` itself (with Kompetenzstufe suffix `.c`) was seen directly in search results | [lehrplan21.ch structural notes, cached](https://www.lehrplan21.ch) |
| MA.1.C | Zahl und Variable — Mathematisieren und Darstellen | Verified | eblb.ch (cached) |
| MA.1.C.1 | Terme umformen und Gleichungen lösen | Verified (content) | eblb.ch (cached) |
| MA.2.A | Form und Raum — Operieren und Benennen | Verified | sg.lehrplan.ch (cached) |
| MA.2.A.1 | Flächeninhalt, Kantenlängen, Oberfläche und Volumen berechnen | Verified (content quoted near-verbatim from search cache) | sg.lehrplan.ch (cached) |
| MA.2.A.2 | Den Satz des Pythagoras anwenden | **Approximate** — Pythagoras is confirmed cycle-3 content of MA.2, but this exact wording/code pairing is our reconstruction | not independently confirmed |
| MA.2.C | Form und Raum — Mathematisieren und Darstellen | Verified | eblb.ch (cached) |
| MA.2.C.1 | Ansichten und Netze darstellen | Verified (content) | eblb.ch / search cache |
| MA.3.A | Grössen, Funktionen, Daten und Zufall — Operieren und Benennen | Verified | hazu.swiss / v-fe.lehrplan.ch (cached) |
| MA.3.A.2 | Grössen schätzen, messen, umwandeln, runden, damit rechnen | Verified (content) | search cache |
| MA.3.A.3 | Funktionale Zusammenhänge beschreiben, Funktionswerte bestimmen | Verified (content) | search cache |
| MA.3.B | Grössen, Funktionen, Daten und Zufall — Erforschen und Argumentieren | Verified | search cache |
| MA.3.B.2 | Sachsituationen zu Statistik, Kombinatorik, Wahrscheinlichkeit erforschen | Verified (content) | search cache |
| MA.3.C | Grössen, Funktionen, Daten und Zufall — Mathematisieren und Darstellen | Verified | search cache |
| MA.3.C.1 | Daten erheben, ordnen, darstellen, auswerten | Verified (content) | search cache |
| MA.3.C.2 | Sachsituationen mathematisieren, Ergebnisse interpretieren | Verified (content) | search cache |

Official entry point: [lehrplan21.ch](https://www.lehrplan21.ch) and cantonal viewers
such as [zh.lehrplan.ch](https://zh.lehrplan.ch), [sg.lehrplan.ch](https://sg.lehrplan.ch).
All direct fetches from this session returned HTTP 403; the "cached" sources above are
search-engine cached extracts of those same official pages, cross-checked against each
other and against the confirmed code grammar (`MA.<Kompetenzbereich>.<Handlungsaspekt>.<Nummer>.<Kompetenzstufe>`).

### PER (anchor language: French)

| Code | Official/approximate title (French anchor) | Status | Source |
|---|---|---|---|
| MSN 31 | Poser et résoudre des problèmes pour modéliser le plan et l'espace | Verified | Fribourg PAF PDF (coveveyse.ch), corroborated by CIIP PDF structure |
| MSN 31.1 | Figures planes, transformations et isométries | **Approximate** — our own sub-grouping; not an official CIIP sub-code | our synthesis of PER content areas |
| MSN 31.2 | Théorème de Pythagore et relations métriques dans le triangle rectangle | **Approximate** — our own sub-grouping; Pythagoras is confirmed PER cycle-3 content (Grandeurs et mesures / Espace) | our synthesis |
| MSN 31.3 | Solides : représentations, vues et développements | **Approximate** — our own sub-grouping | our synthesis |
| MSN 32 | Poser et résoudre des problèmes pour construire et structurer des représentations des nombres réels | **Verified verbatim** | [Fribourg PAF PDF](https://coveveyse.ch/wp-content/uploads/2023/10/DISCIPLINES_MAT_PAF.pdf), p.3 |
| MSN 32.1 | Nombres réels : entiers, décimaux, fractions et nombres relatifs | **Approximate** — our own sub-grouping of confirmed PER themes (nombres naturels/décimaux, relatifs, fractions) | Fribourg PAF PDF, our synthesis |
| MSN 32.2 | Propriétés des nombres et des opérations pour établir des preuves | **Approximate** sub-grouping; phrase "utilisation des propriétés des nombres et opérations pour établir des preuves" is verbatim from the Fribourg PAF PDF | Fribourg PAF PDF, p.3 |
| MSN 33 | Résoudre des problèmes numériques et algébriques | **Verified verbatim** — read directly from the official CIIP PDF | [PER_print_MSN_33.pdf](https://bdper.plandetudes.ch/uploads/per_pdf/Mathematiques_et_sciences_de_la_nature/Mathematiques/PER_print_MSN_33.pdf), CIIP 2010 |
| MSN 33.1 | Algèbre — calcul littéral | **Verified verbatim** heading, from the official CIIP PDF | PER_print_MSN_33.pdf |
| MSN 33.2 | Algèbre — équations (et systèmes d'équations) | **Verified verbatim** heading "Algèbre – Équations"; "systèmes d'équations" content confirmed in the same PDF | PER_print_MSN_33.pdf |
| MSN 33.3 | Fonctions et proportionnalité | **Verified** — "Fonctions" heading and "Résolution de problèmes de proportionnalité (…échelle, pourcentage, pente…)" quoted directly | PER_print_MSN_33.pdf |
| MSN 33.4 | Diagrammes : lecture, interprétation et réalisation | **Verified verbatim** heading "Diagrammes"; sub-content ("lecture de données…", "réalisation de diagrammes") quoted directly | PER_print_MSN_33.pdf |
| MSN 34 | Mobiliser la mesure pour comparer des grandeurs | **Verified verbatim** | Fribourg PAF PDF, p.3 |
| MSN 34.1 | Aires et périmètres de figures planes | **Approximate** sub-grouping | our synthesis |
| MSN 34.2 | Volumes et aires de solides | **Approximate** sub-grouping | our synthesis |
| MSN 35 | Modéliser des phénomènes naturels, techniques, sociaux ou des situations mathématiques | **Verified verbatim** | Fribourg PAF PDF, p.3; CIIP PDF fold-out flap text |

Official entry point: [plandetudes.ch](https://www.plandetudes.ch) (redirects to a
JavaScript portal at `portail.ciip.ch` that this session could not fetch as static
text) and the CIIP's own PDF repository at
[bdper.plandetudes.ch](https://bdper.plandetudes.ch). The `PER_print_MSN_33.pdf` fetch
is the strongest source in this seed: it is the actual CIIP-published print layout,
extracted with `pdftotext`, not a search summary.

**Net assessment**: the five PER area codes (`MSN 31`–`MSN 35`) and four of `MSN 33`'s
four thematic headings are verified against an official CIIP document. Every deeper
subdivision (`MSN 3x.n`) is our own organisational layer on top of verified content,
built for exercise-tagging granularity, and is disclosed as such rather than presented
as an official CIIP number. On the LP21 side, the three-level code grammar and the
general competency-area texts are verified against cached official pages; a handful of
specific competency/code pairings (flagged "Approximate" above, notably `MA.2.A.2` for
Pythagoras) are reconstructed in the confirmed style because a live fetch of the exact
paragraph was blocked.

## 6. Demo exercise corpus

`apps/api/alppy/seed/data/exercises.json` contains 63 original exercises (none copied
from any textbook), evenly split between French (32) and German (31), spread across
all 7 chapters and difficulty levels 1–5. They represent what the ingestion pipeline
would have extracted from an uploaded French or German textbook, which is why
`language` is fixed per exercise regardless of a teacher's UI locale. 8 are `open`
(printable, never auto-graded — see `docs/plan.md` §3 on the grader's explicit
`NotGradeable` path); the rest are `mcq` (41, always 3–4 options, one correct) or
`true_false` (14). Every multiple-choice distractor was written to match a specific,
plausible calculation mistake (named in `explanation`) rather than being an arbitrary
wrong number — this is what makes per-competency mastery meaningful: a wrong answer
should be diagnostic, not noise.
