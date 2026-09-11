#!/usr/bin/env python
"""Regenerate the PER cycle-3 mathematics seed from CIIP's own API.

The seed carried sixteen PER rows, five of them the real objectif codes and
eleven invented — `MSN 31.2` is not a CIIP code, and it was written in CIIP's
notation, so a teacher reading one off a printed sheet had no way to know their
inspector would not recognise it (database audit H1, H3).

This fetches the real thing. `per.ciip.ch/api` is CIIP's own service behind the
public PER viewer, and it returns the whole structure as JSON — which is a
better primary source than the print PDFs the audit suggested parsing: the
levels are fields rather than indentation, and re-running this is how the seed
gets updated when CIIP publishes again.

    python scripts/fetch-per-curriculum.py

Writes ``apps/api/alppy/seed/data/per_msn_cycle3.json``. Nothing calls it at
seed time: `docker compose up` must work with no network, so the fetched data
is committed and the seed reads the file.

**What it extracts, and the shape it lands in**

    domaine      MSN                  Mathématiques et Sciences de la nature
    objectif     MSN 31 … MSN 35      the five cycle-3 maths objectives
    composante   MSN 31.C1 … .C8      the numbered continuations
    progression  MSN 31.P4841         what is taught, carrying its year
    attente      MSN 31.A2723         attentes fondamentales

Only the objectif codes are CIIP's own notation. The rest are derived, and
derived deterministically: a composante from its position (CIIP prints them
1-8), a progression and an attente from CIIP's own row id, which is stable
across fetches and is what makes `source_ref` checkable. They are marked
official because the TEXT is the publisher's, and `source_ref` names the
endpoint it came from so the claim can be audited rather than trusted.

**Where a progression attaches.** CIIP marks the composante a learning belongs
to inline, as a bracketed number — "Utilisation du théorème de Pythagore
(Niv 2-3) ( 8 )" hangs off composante 8. Those markers are parsed; a learning
with none attaches to the objectif, which is what the source says by not
saying.

**French only, deliberately.** The PER is a French-language curriculum and its
text is normative. Translating it here would put words in CIIP's mouth, and the
label lookup already falls back (`labels[locale] or labels["fr"]`).
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "apps" / "api" / "alppy" / "seed" / "data" / "per_msn_cycle3.json"

API = "https://per.ciip.ch/api"
EDITION = "2023"
"""CIIP's current published PER. Recorded so a future fetch lands beside this
one rather than on top of it — which is the whole point of `edition_id`."""

#: CIIP's internal learning-objective ids for cycle-3 mathematics, resolved
#: from /api/disciplines. Pinned rather than re-derived so a fetch is
#: reproducible and reviewable; the script checks the code it gets back.
OBJECTIVES = {49: "MSN 31", 62: "MSN 32", 63: "MSN 33", 61: "MSN 34", 65: "MSN 35"}

#: "… ( 8 )" or "… (8)" at the end of a learning — CIIP's own marker for the
#: composante it belongs to.
_COMPONENT_REF = re.compile(r"\(\s*(\d{1,2})\s*\)\s*$")
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _get(path: str) -> Any:
    with urllib.request.urlopen(f"{API}{path}", timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _text(html: str | None) -> str:
    """CIIP returns rich text; the seed stores what a teacher would read."""
    return _WS.sub(" ", _TAG.sub(" ", html or "").replace("&nbsp;", " ")).strip()


def _years(node: dict[str, Any]) -> list[str]:
    seen = {
        y["year"]
        for dist in node.get("yearDistributions") or []
        for y in dist.get("years") or []
    }
    return [f"{y}H" for y in sorted(seen)]


def _row(
    code: str,
    *,
    kind: str,
    parent: str | None,
    label: str,
    source: str,
    year: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "kind": kind,
        "parent_code": parent,
        "year": year,
        "labels": {"fr": label},
        "description": {"fr": description} if description else {},
        "is_official": True,
        "source_ref": source,
    }


def _objective(lo_id: int, expected_code: str) -> list[dict[str, Any]]:
    data = _get(f"/learning-objectives/{lo_id}")
    code = data["code"]
    if code != expected_code:
        raise SystemExit(
            f"CIIP objective {lo_id} is now {code!r}, not {expected_code!r} — "
            "the pinned ids are stale; re-resolve them from /api/disciplines"
        )
    source = f"{API}/learning-objectives/{lo_id}"
    rows = [
        _row(
            code,
            kind="objectif",
            parent="MSN",
            label=data["name"],
            source=source,
            description=_text(data.get("generalDescription", {}).get("text"))[:2000] or None,
        )
    ]

    # --- composantes, numbered as CIIP prints them (1-based).
    by_position: dict[int, str] = {}
    for component in sorted(data["components"], key=lambda c: int(c["position"])):
        number = int(component["position"]) + 1
        child = f"{code}.C{number}"
        by_position[number] = child
        rows.append(
            _row(
                child,
                kind="composante",
                parent=code,
                label=_text(component["text"]),
                source=source,
            )
        )

    # --- progressions and their attentes fondamentales.
    for section in data["progressionSections"]:
        section_name = _text(section.get("name")) or None
        for progression in section.get("progressions") or []:
            for learning in progression.get("learnings") or []:
                label = _text(learning["content"]["html"])
                if not label:
                    continue
                marker = _COMPONENT_REF.search(label)
                parent = by_position.get(int(marker.group(1))) if marker else None
                years = _years(learning) or [None]
                for year in years:
                    suffix = f".{year}" if year and len(years) > 1 else ""
                    rows.append(
                        _row(
                            f"{code}.P{learning['id']}{suffix}",
                            kind="progression",
                            parent=parent or code,
                            label=label,
                            source=source,
                            year=year,
                            description=section_name,
                        )
                    )
            for expectation in progression.get("fundamentalExpectations") or []:
                label = _text(expectation["content"]["html"])
                if not label:
                    continue
                rows.append(
                    _row(
                        f"{code}.A{expectation['id']}",
                        kind="attente",
                        parent=code,
                        label=label,
                        source=source,
                        description=section_name,
                    )
                )
    return rows


def main() -> int:
    rows: list[dict[str, Any]] = [
        _row(
            "MSN",
            kind="domaine",
            parent=None,
            label="Mathématiques et Sciences de la nature",
            source=f"{API}/disciplines",
        )
    ]
    for lo_id, code in OBJECTIVES.items():
        print(f"fetching {code} (id {lo_id})…", file=sys.stderr)
        rows.extend(_objective(lo_id, code))

    codes = [r["code"] for r in rows]
    duplicates = {c for c in codes if codes.count(c) > 1}
    if duplicates:
        raise SystemExit(f"derived codes are not unique: {sorted(duplicates)}")
    known = set(codes)
    dangling = {r["parent_code"] for r in rows} - known - {None}
    if dangling:
        raise SystemExit(f"rows point at parents that were not fetched: {sorted(dangling)}")

    OUT.write_text(
        json.dumps(
            {"curriculum": "PER", "edition": EDITION, "cycle": 3,
             "subject_key": "mathematics", "competencies": rows},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    print(f"wrote {OUT.relative_to(ROOT)}: {len(rows)} rows {counts}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
