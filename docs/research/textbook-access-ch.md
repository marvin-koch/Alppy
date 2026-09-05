# Can Swiss (Deutschschweiz + Suisse romande) textbooks be accessed programmatically?

Status: research note, not legal advice. Written 2026-09-05. Every claim in the "Verified" sections
carries a source URL that was actually fetched on that date; anything not backed by a fetched
source is explicitly marked as unverified or as a search-engine summary (lower confidence than a
primary document).

## 0. The question, precisely

Alppy's RAG pipeline needs textbook content in the index. Two separate questions:

1. **Technical**: is there a machine-readable feed (PDF export, API, bulk digital edition) for the
   textbooks actually used in Sek I / cycle 3 classrooms?
2. **Legal**: if Alppy (a third-party SaaS, not the school itself) obtains that content and indexes
   it for retrieval-augmented generation, is that a licensed use?

These are independent. A publisher can hand out clean PDFs and still forbid third-party indexing
in its licence terms; conversely a locked-down platform tells you nothing about the copyright
question. Both are covered below, per publisher/body.

## 1. Market structure — who publishes what

| Body | Region | Role | Verified |
|---|---|---|---|
| **Lehrmittelverlag Zürich (LMVZ)** | ZH, sold cantons-wide | Cantonal publisher, largest Deutschschweiz Lehrmittelverlag | Yes |
| **Klett und Balmer AG** | Deutschschweiz | Private publisher, major Lehrmittel supplier (owned by Ernst Klett Verlag, DE) | Yes |
| **Schulverlag plus AG** (part of **hep Verlag** group) | Deutschschweiz, esp. BE/cantons using the "Schulverlag" line | Publisher for several cantonal mandates | Yes |
| **ilz — Interkantonale Lehrmittelzentrale** | 21 Deutschschweiz cantons + Liechtenstein | Coordination body, not a publisher or distributor; supports cantons in ensuring Lehrmittel quality and coordinates commissioning | Yes |
| **CIIP** (Conférence intercantonale de l'instruction publique de la Suisse romande et du Tessin) | Suisse romande | Commissions and owns the *moyens d'enseignement romands* (MER), PER-aligned, produced with Swiss/international publishers, distributed via Tenausys SA / Novapro Shop | Yes |
| **Edubase AG** | Switzerland-wide | Cross-publisher e-book platform for Lehrmittel (200+ publishers, 6000+ titles), CH-hosted | Yes |
| Cantonal **Lehrmittelliste / Lehrmittelverzeichnis** | Each canton | The binding list of approved (obligatorisch / alternativ-obligatorisch) textbooks for that canton — this, not ilz, is the actual gatekeeper of what a given school may use | Yes (seen for ZH) |

### Verified — with source URL and date accessed

- LMVZ sells "digital" licences (e.g. *Deutsch Sieben bis Neun digital für Lehrpersonen*) as a
  **school licence**, CHF 46.00 incl. VAT (school price, 25% under list), running 01.01–31.08 of
  the following year, one seat per teacher, transferable once if a teacher leaves. The product
  page does not publish machine-readable export/API terms; general terms are referenced but not
  linked inline.
  Source: [LMVZ Webshop — Deutsch Sieben bis Neun digital für Lehrpersonen](https://shop.lmvz.ch/de/Katalog/Deutsch/Deutsch-Sieben-bis-Neun-digital-fuer-Lehrpersonen-10315.html), accessed 2026-09-05.
- LMVZ also publishes the canton's own approved-textbook register.
  Source: [Kanton Zürich — Verzeichnis der obligatorischen Lehrmittel 2025/26 (PDF)](https://www.zh.ch/content/dam/zhweb/bilder-dokumente/themen/bildung/informationen-fuer-schulen/informationen-fuer-die-volksschule/unterricht/lehrmittel/lehrmittelverzeichnis_2025_26_ua.pdf), accessed 2026-09-05.
- Klett und Balmer's digital-edition licence (**meinklett.ch**) is a locked-down web app / device
  app, not a document format. The special licence terms state explicitly: *"the use of the Digital
  Edition by third parties is prohibited"*; extraction to external storage is forbidden except for
  ordinary device backup; copying, sharing, or extracting "data or data elements" is forbidden;
  reverse engineering and removal of watermarks are forbidden; commercial use/resale is forbidden.
  Source: [Klett und Balmer — Lizenz-Sonderbestimmungen für die Nutzung der digitalen Ausgabe](https://www.klett.ch/lizenz-sonderbestimmungen/lizenz-sonderbestimmungen-fuer-die-nutzung-der-digitalen-ausgabe), accessed 2026-09-05.
- Schulverlag plus's digital offer is delivered through a "Cockpit" (class-code based access,
  Kahoot-style), with per-title digital licences purchasable directly or procured centrally by
  cantonal Lehrmittel offices. No mention of bulk PDF export or API.
  Source: [Schulverlag plus — Alles digital, vom Kauf der Lizenz bis zur Nutzung](https://www.schulverlag.ch/de/aktuelles/alles-digital-vom-kauf-der-lizenz-bis-zur-nutzung/), accessed 2026-09-05.
- hep Verlag's digital titles are distributed as e-book coupons redeemed in the "beook" app; "almost
  all" hep teaching materials have a fully digitised edition.
  Source: [hep Verlag — eLehrmittel / beook](https://www.hep-verlag.ch/elehrmittel), accessed 2026-09-05.
- ilz describes itself as *"das Kompetenzzentrum für Lehrmittel der Deutschschweizer Kantone"*,
  coordinating quality and commissioning of Lehrmittel across 21 cantons + Liechtenstein. The page
  fetched does **not** describe any API, digital-format standard, or third-party licensing terms —
  ilz is a coordination body, not a rights-holder or distributor, so it is not a licensing point of
  contact for Alppy.
  Source: [ilz.ch — Lehrmittel](https://ilz.ch/lehrmittel), accessed 2026-09-05; corroborated by [Interkantonale Lehrmittelzentrale — Wikipedia](https://de.wikipedia.org/wiki/Interkantonale_Lehrmittelzentrale) (unverified secondary source, used only for the member-canton list, not fetched directly — flagged below).
- CIIP's moyens d'enseignement romands (MER) page confirms MER are the official PER-aligned
  materials for compulsory schooling across seven disciplines, produced with Swiss/international
  publishers and distributed in print and digital form via Tenausys SA / the Novapro Shop. The
  fetched page makes **no mention** of an API, bulk PDF download, or third-party licensing regime.
  Source: [CIIP — Moyens d'enseignement romands](https://www.ciip.ch/Instruction-publique/Moyens-denseignement-romands), accessed 2026-09-05.
- The *Mathématiques 9-10-11* line (new edition 2024–2026) is CIIP-edited; its teacher guide is
  published "exclusively online" on the **ESPER** platform, gated behind an **Edulog** identity
  (the Swiss federated school-login system), not a public or bulk-downloadable resource.
  Source: search-engine synthesis of [CIIP — Mathématiques, 9-10-11 - AM](https://www.ciip.ch/Moyens-denseignement/-Mathematiques-cycle-3/Mathematiques-9-10-11-AM), accessed 2026-09-05 (page itself was not independently re-fetched for this specific claim — see caveat below).
- **Anthropic's own documentation states plainly**: *"Anthropic does not offer its own embedding
  model."* Irrelevant to textbook access directly, but relevant to the parallel ADR on embeddings
  (§0001) — repeated here because the brief asked this file to verify it.
  Source: [Anthropic — Embeddings](https://platform.claude.com/docs/en/build-with-claude/embeddings), accessed 2026-09-05.

### Needs human confirmation

- Exact current AGB/licence text for LMVZ digital products beyond the one product page fetched —
  the page links out to "AGB und Lizenzbedingungen" that were not independently fetched.
- Whether **Edubase** (the cross-publisher e-book platform, CH-hosted, 200+ publishers, 6000+
  titles) offers any institutional or API-level access beyond its consumer e-reader — its own
  marketing pages describe an e-book reading app, not a data feed; no evidence either way of a
  publisher- or platform-level bulk-content or API programme was found.
  Source: [Edubase — Lernen und Arbeiten mit E-Books](https://www.edubase.ch/), accessed 2026-09-05 (marketing copy only; no API/ToS page fetched).
- Whether any Deutschschweiz or Suisse romande publisher offers a **content or embeddings API**
  intended for third-party edtech integration (as opposed to a locked reader app). No search
  turned up such a programme for LMVZ, Klett und Balmer, Schulverlag plus/hep, or CIIP/Tenausys.
  Absence of evidence is not proof of absence — this needs a direct partnership inquiry per
  publisher (see Recommendation).
- ilz's membership list of 21 cantons + Liechtenstein was corroborated only via Wikipedia (not an
  authoritative primary source); treat as indicative, confirm against ilz's own "Organisation" page
  before quoting in anything contractual.

## 2. Digital access format, by publisher

| Publisher | Format offered | DRM / lock-in | API for third parties | Verified |
|---|---|---|---|---|
| LMVZ | Web-based "digital" edition bundled with print licence | Account/licence-gated (school licence, seat-based) | None found | Partial |
| Klett und Balmer | Web app (meinklett.ch) + device app | Explicit anti-extraction clause, no third-party use, no offline copy beyond device backup | None; explicitly prohibited | Yes |
| Schulverlag plus | "Cockpit" web platform, class-code access | Account-gated | None found | Partial |
| hep Verlag | beook app (e-book reader), coupon-redeemed | Account/app-gated | None found | Partial |
| CIIP / MER | Print + digital (via Tenausys SA / Novapro), teacher guides via ESPER (Edulog login) | Account/login-gated | None found | Partial |
| Edubase (cross-publisher) | E-book reader app | Account-gated, CH-hosted | Unclear — no evidence found either way | No |

**Bottom line on the technical question**: every mainstream Deutschschweiz and Suisse romande
Lehrmittel publisher checked distributes digital content through a **closed, account-gated reader
platform**, not a bulk file or API. Where terms were fetched (Klett und Balmer), third-party use
and extraction are **explicitly and specifically prohibited**. There is no publicly documented path
for a third-party SaaS to pull textbook content programmatically from any of these publishers today.

## 3. Legal framing under Swiss copyright law (URG)

This section describes what the primary sources say. It is **not** a legal opinion on whether
Alppy's specific architecture is compliant — that requires counsel, per publisher and per use case.

### Art. 19 URG — Eigengebrauch (use for own/private purposes)

Verified via direct text lookup:

- Art. 19 para. 1 lit. b permits **a teacher** to use a published work "im Unterricht" (in
  classroom teaching) as a form of privileged personal use ("Eigengebrauch").
- Art. 19 para. 2 permits **engaging a third party** to make the copies — but the text names the
  example of libraries and institutions that provide copying equipment to their own users, not a
  remote SaaS that stores and indexes the work.
- Art. 19 para. 3 restricts this: outside the strict private/family circle, **complete or largely
  complete reproduction of commercially available work copies is not permitted** — only excerpts.
- Art. 19 para. 3bis carves out an exception for copies incidentally made while retrieving works
  that were **lawfully made accessible** (a technical/caching exception, not a green light for
  wholesale re-hosting).

Source: [swissrights.ch — Art. 19 URG (2022 consolidated text)](https://www.swissrights.ch/gesetze/Artikel-19-URG-2022-DE.php), accessed 2026-09-05.

### GT 7 — Gemeinsamer Tarif 7 (ProLitteris), the school blanket licence

This is the tariff that actually operationalises Art. 19/20/38 URG compensation for schools. Full
text fetched and read directly (not a search summary):

- **Scope of "Nutzer" (licensees) (§1.1–1.4)**: schools, their students, teachers, and staff, for
  reproduction "zu Zwecken des Unterrichts" (Art. 19 §1 lit. b URG). This is an enumerated list of
  school types (obligatorische Schule incl. Sek I, Sek II, tertiary, private schools, further
  training) — it is a **school-side** licence, not a service-provider licence.
- **Third parties (§1.3, explicitly limited)**: *"Als Nutzer gelten auch Dienstleister, die
  Vervielfältigungen im Auftrag einer Schule herstellen [...], soweit sie Sendungen direkt aus
  einem Radio- oder TV-Programm als einziger Quelle vervielfältigen und anschliessend in einer
  Schule zugänglich machen."* — i.e. the tariff extends "user" status to third-party service
  providers **only for broadcast-recording services** (media-monitoring/documentation/copy
  services recording radio/TV). For anything else done by a third party, the tariff says GT 8 and
  GT 9 apply instead. **A SaaS that stores and indexes textbook PDF content is not the kind of
  "Dritte" this tariff licenses.**
- **"Nur intern" (§2.2 lit. a)**: permitted reproduction must stay internal — internal
  distribution/making-accessible including download is fine (server, intranet, etc.), but there
  must be **no systematic distribution or access outside the school's own teaching** and **no use
  by external persons**. A multi-tenant SaaS platform hosted outside the school, serving many
  schools from one shared index, sits in a legal grey zone against this "internal only" condition.
- **"Nur Ausschnitte" (§2.2 lit. b)**: for commercially available work copies (books, journals,
  etc.), **only excerpts** may be reproduced — not the whole work. A RAG pipeline that ingests and
  indexes entire textbook chapters/volumes goes beyond what this clause licenses; a pipeline
  restricted to teacher-selected excerpts is closer to (but not proven to be inside) the licensed
  scope.
- **Compensation (§3)**: a per-student annual fee is owed by the school (e.g. CHF 1.41/student for
  paper copies + CHF 0.52/student for digital copies at compulsory-school level, public schools),
  collected via cantons/school administrations — not something a third-party vendor pays on the
  school's behalf, and not a mechanism that grants the vendor any rights of its own.

Source: [ProLitteris — Gemeinsamer Tarif 7 (GT 7), 2022–2026, full PDF](https://content.prolitteris.ch/uploads/documents/GT_7_Schulen_2022_de.pdf), accessed 2026-09-05, fetched and read in full (§§1–3).

### Reading these two sources together

GT 7 is the school's blanket licence for **photocopying/scanning excerpts for their own in-class
use**. Nothing in the text fetched extends that licence to a third-party SaaS ingesting, storing,
and running retrieval/generation over textbook content on infrastructure the vendor controls, for
multiple schools. The narrow "Dritte" carve-out in §1.3 is specific to broadcast recording and does
not generalise to document digitisation services.

**This strongly suggests — but a fetched tariff document is not a legal opinion, so this must be
treated as "needs human confirmation" — that GT 7 / Art. 19 URG do *not* cover a third-party RAG
SaaS indexing full textbook PDFs, even when the end-user is a licensed teacher at a licensed
school.** The legally cleaner reading of the sources gathered here is that this would require a
**separate agreement directly with the rights holder (the publisher)**, not reliance on the
school's existing blanket tariff.

### Needs human confirmation (legal)

- Whether a Swiss lawyer specialising in URG/copyright and edtech agrees with the reading above.
- Whether any publisher (LMVZ, Klett und Balmer, Schulverlag plus/hep, CIIP) has an existing or
  precedent-setting agreement with a third-party edtech/RAG vendor that would establish a workable
  contract template.
- Whether transient/ephemeral vector indexing (embeddings, not stored raw text) changes the
  analysis — Art. 19 §3bis's "Vervielfältigungen beim Abrufen" (incidental copies on retrieval)
  exception was written for caching/browsing, not for training or embedding a document for
  indefinite semantic search; whether an embedding-only index (never returning verbatim source
  text back to the model, only chunk IDs/citations) meaningfully reduces exposure is a live
  question for counsel, not something the tariff text answers.
- Whether the teacher's *own* upload of a textbook they personally licensed, into a
  single-tenant/self-hosted Alppy instance used only by that teacher's own class, changes the
  analysis relative to a shared multi-tenant SaaS (see Recommendation — this is the MVP's actual
  posture and is a materially different, and much safer, case than a vendor bulk-licensing content
  itself).

## 4. Suisse romande specifics

- CIIP commissions and centrally distributes MER; ~500 CIIP-owned titles plus ~250 third-party
  titles for vocational/secondary II, produced with Tenausys SA and sold via the Novapro Shop.
  Source: [CIIP — Moyens d'enseignement romands](https://www.ciip.ch/Instruction-publique/Moyens-denseignement-romands), accessed 2026-09-05.
- The GT 7 tariff and Art. 19 URG apply Confederation-wide, including Suisse romande and (via a
  parallel FL-URG regime) Liechtenstein — there is no separate romande copyright regime, only a
  separate content-commissioning body (CIIP instead of the cantonal Deutschschweiz publishers).
- No evidence was found of a romande-specific API or bulk-access programme distinct from the
  German-speaking situation; the same "closed platform, login-gated" pattern applies (ESPER for
  Mathématiques 9-10-11).

## 5. Caveats on method

- Some claims above rely on WebSearch result summaries rather than a directly fetched page (marked
  inline as "search-engine synthesis" or "Partial"/"No" in tables). Where a fetch failed (e.g. the
  Swiss ESchK mirror of GT 7 returned 404; a lawbrary.ch mirror of Art. 19 returned 403) an
  alternate, working source was found and used instead — both are noted.
- No French-language primary source (klett.ch equivalent, CIIP licence terms) was fetched in full
  for a licence-terms document — only the CIIP overview page. If Alppy pursues romande textbooks
  specifically, repeat the Klett-style licence-terms fetch for the actual romande publisher
  contracts before relying on this note.
- This document does not constitute, and should not be treated as, legal advice.

## 6. Recommendation

**The MVP does not depend on the outcome of any of this.** Alppy's ingestion pipeline takes
teacher-uploaded PDFs: the teacher supplies material they already licitly possess (their own
purchased textbook, a scanned worksheet they wrote, an open-licence resource), Alppy never fetches,
stores, or redistributes publisher content on its own initiative, and the repository ships only a
small, fully self-authored demo corpus (invented exercises, not excerpts of any real Lehrmittel).
Under this model Alppy is a tool the teacher uses on content the teacher is already responsible
for — the same posture as a photocopier or a personal scanning app — and the analysis above is
useful context, not a blocker.

This has a real limit: it puts the burden of "am I allowed to upload this" on the teacher, and
Alppy should say so in-product (a short notice at upload time, not a legal shield, but honest UX).
It also means Alppy cannot claim "pre-loaded with your textbook" as a feature for the MVP.

**Path to publisher partnership, if Alppy wants pre-indexed textbook content later:**

1. Treat this as a **commercial negotiation, not a copyright workaround**. GT 7 does not appear
   (per §3 above) to license third-party SaaS indexing; do not build on the assumption that it
   does.
2. Approach LMVZ, Klett und Balmer, and Schulverlag plus/hep directly — they are the three
   Deutschschweiz publishers actually seen in this research, all already run gated digital
   platforms, and all would need to agree to release chunked/embeddable content to a third party.
   Lead with a narrow pilot: one subject, one canton, opt-in schools already licensed for that
   title, with the publisher able to revoke access.
3. Approach CIIP/Tenausys in parallel for the Suisse romande MER line, since it is a distinct
   commissioning body with its own contracts.
4. Have Swiss counsel confirm whether embeddings-only (no verbatim storage, retrieval returns
   citations rather than full text back to the model) materially changes the negotiating position
   — it likely helps the pitch even if it does not change the legal baseline.
5. In parallel, build Alppy's retrieval and provenance UI to be **publisher-agnostic and
   source-attributed** regardless — the same "chunk + page + citation" data model works whether the
   source is a teacher's own upload or a future licensed feed, so no rework is needed if/when a
   partnership lands.
