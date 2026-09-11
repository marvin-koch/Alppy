#!/usr/bin/env python
"""Measure whether the vision grader still reads an answer the way it did.

Nothing else in the repo does. `PROMPT_VERSION` moved v2 → v3 with nothing
measuring the effect on a real model: the existing prompt test proves the two
agree on a FAKE provider, which is a statement about routing rather than about
reading (T9). And the prompt-injection defence is tested only through the
model's own self-reported flag, so nothing says a real model raises that flag
when shown instruction-shaped writing (T12).

What this reports
-----------------
* a confusion matrix over ``{correct, wrong, blank, not_gradeable}`` — expected
  verdict against the one the grader produced;
* the transcription exact-match rate, normalised for case and whitespace only.

Both are compared against ``baseline.json``. A run that falls more than the
declared margin below it exits 1.

Why both numbers, and why the matrix rather than an accuracy
------------------------------------------------------------
One accuracy figure hides which direction it moved in, and the directions are
not equivalent. Reading a wrong answer as ``correct`` costs a child a mark they
did not earn and nobody notices. Reading a correct one as ``wrong`` is visible
to the teacher on the review screen and gets fixed. Grading a blank at all is
the one the product forbids outright. A single number treats all three as the
same event.

The transcription rate is separate because it moves first: a prompt change
usually degrades the reading before it degrades the verdict, and by the time the
verdict moves the cause is several edits back.

What it does NOT do
-------------------
Call the grading service. It sends the crop through the same prompt the product
sends — ``load_prompt(PROMPT_NAME, PROMPT_VERSION)`` with the same values — and
reads the same fields. Going through ``grade_one`` would need a database, a
storage backend and a Detection row per sample, and would measure the plumbing
rather than the prompt. When the plumbing is what you want, that is
``test_open_grading.py``.

Usage
-----
    PYTHONPATH=apps/api python scripts/run-golden-set.py
    PYTHONPATH=apps/api python scripts/run-golden-set.py --update-baseline
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

GOLDEN = ROOT / "apps" / "api" / "tests" / "golden"
VERDICTS = ("correct", "wrong", "blank", "not_gradeable")


def _normalise(text: str | None) -> str:
    """Case and whitespace only.

    Deliberately NOT more: stripping punctuation would make "3/3" and "33"
    the same string, and the whole point of the transcription rate is that it
    notices small degradations before the verdict does.
    """
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _verdict_of(data: dict[str, Any]) -> str:
    """The grader's own decision rules, in the order `grade_one` applies them."""
    if data.get("instruction_like"):
        # The defence: an instruction in the box is never a graded answer,
        # whatever confidence the model reported for it.
        return "not_gradeable"
    if data.get("written") is False:
        return "blank"
    correct = data.get("correct")
    if correct is True:
        return "correct"
    if correct is False:
        return "wrong"
    return "not_gradeable"


def run(samples: list[dict[str, Any]]) -> dict[str, Any]:
    from alppy.ai.base import ImagePart
    from alppy.ai.client import AiClient, load_prompt, parse_json_response
    from alppy.services.open_answer_grading import (
        NO_EXPECTED_ANSWER,
        PROMPT_NAME,
        PROMPT_VERSION,
    )

    ai = AiClient()
    prompt = load_prompt(PROMPT_NAME, PROMPT_VERSION)
    if not ai.chat_is_grounded:
        # Said out loud rather than reported as a score. The offline providers
        # answer every crop the same way, so a matrix built from them measures
        # the harness and nothing else — and a green run that means nothing is
        # worse here than a red one.
        print(
            "\n!! the configured chat provider is NOT grounded (echo/no key).\n"
            "   The numbers below exercise the harness; they say nothing about\n"
            "   recognition. Set a real provider to measure anything.\n"
        )

    matrix: dict[str, dict[str, int]] = {e: dict.fromkeys(VERDICTS, 0) for e in VERDICTS}
    transcriptions_right = 0
    rows: list[dict[str, Any]] = []

    for sample in samples:
        image = (GOLDEN / "crops" / sample["crop"]).read_bytes()
        try:
            response, _record = ai.complete(
                prompt=prompt,
                purpose=PROMPT_NAME,
                values={
                    "language": sample["language"],
                    "statement": sample["statement"],
                    "reference": sample["expected_answer"] or NO_EXPECTED_ANSWER,
                    "fill": "LINED",
                },
                images=(ImagePart(image),),
                # No roster: these crops are not a child's paper, so there is no
                # name for the gate to find and nothing to scrub. A real crop in
                # this corpus would change that, which is one more reason the
                # README says not to add one casually.
                student_names=[],
                temperature=0.0,
            )
            data = parse_json_response(response.text)
        except Exception as exc:  # noqa: BLE001 — reported per sample, never swallowed
            data = {"_error": f"{type(exc).__name__}: {exc}"}

        got = "not_gradeable" if "_error" in data else _verdict_of(data)
        want = sample["expected_verdict"]
        matrix[want][got] += 1

        said = _normalise(data.get("transcription"))
        meant = _normalise(sample["expected_transcription"])
        exact = said == meant
        transcriptions_right += int(exact)

        rows.append(
            {
                "id": sample["id"],
                "case": sample["case"],
                "want": want,
                "got": got,
                "transcription_exact": exact,
                "said": said,
                "error": data.get("_error"),
            }
        )

    total = len(samples) or 1
    agreed = sum(matrix[v][v] for v in VERDICTS)
    return {
        "grounded": bool(ai.chat_is_grounded),
        "samples": len(samples),
        "verdict_agreement": round(agreed / total, 4),
        "transcription_exact_match": round(transcriptions_right / total, 4),
        "matrix": matrix,
        "rows": rows,
    }


def report(result: dict[str, Any]) -> None:
    print(f"\ngolden set: {result['samples']} samples")
    print(f"  verdict agreement        {result['verdict_agreement']:.1%}")
    print(f"  transcription exact      {result['transcription_exact_match']:.1%}\n")

    width = max(len(v) for v in VERDICTS)
    print(f"  {'expected':>{width}}  " + "  ".join(f"{v:>{width}}" for v in VERDICTS))
    for want in VERDICTS:
        cells = "  ".join(f"{result['matrix'][want][got]:>{width}}" for got in VERDICTS)
        print(f"  {want:>{width}}  {cells}")

    wrong = [r for r in result["rows"] if r["want"] != r["got"]]
    if wrong:
        print("\n  disagreed:")
        for row in wrong:
            detail = row["error"] or f"said {row['said']!r}"
            print(f"    {row['id']}: wanted {row['want']}, got {row['got']} — {detail}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args()

    manifest = json.loads((GOLDEN / "manifest.json").read_text())
    samples = manifest["samples"]
    if not samples:
        print("✗ the manifest lists no samples — an empty corpus passes everything")
        return 2

    result = run(samples)
    report(result)

    baseline_path = GOLDEN / "baseline.json"
    if args.update_baseline:
        baseline_path.write_text(
            json.dumps(
                {
                    "grounded": result["grounded"],
                    "verdict_agreement": result["verdict_agreement"],
                    "transcription_exact_match": result["transcription_exact_match"],
                    "margin": 0.10,
                    "note": (
                        "Accepted by a person who read the matrix above. The margin is "
                        "what a run may fall by before this fails — wide, because the "
                        "corpus is small and a single sample is 12.5%."
                    ),
                },
                indent=2,
            )
            + "\n"
        )
        print(f"\nbaseline updated: {baseline_path.relative_to(ROOT)}")
        return 0

    if not baseline_path.exists():
        print("\n✗ no baseline.json — run once with --update-baseline and read the matrix")
        return 2

    baseline = json.loads(baseline_path.read_text())

    # A number from the offline provider is not a floor for a real one, and a
    # real one is not a floor for the offline provider. Comparing across that
    # line is how a gate comes to pass for a reason nobody intended: an echo
    # baseline of 12.5% is cleared by ANY grounded run, forever, and the gate
    # silently stops being one.
    if bool(baseline.get("grounded")) != result["grounded"]:
        print(
            f"\n✗ the baseline was recorded with grounded={baseline.get('grounded')} "
            f"and this run is grounded={result['grounded']}.\n"
            f"  These are not comparable. Re-baseline with the provider you intend "
            f"to gate on, and read the matrix when you do."
        )
        return 2

    margin = float(baseline.get("margin", 0.10))
    failures = []
    for key in ("verdict_agreement", "transcription_exact_match"):
        floor = float(baseline[key]) - margin
        if result[key] < floor:
            failures.append(
                f"  {key}: {result[key]:.1%} is below {floor:.1%} "
                f"(baseline {float(baseline[key]):.1%} − margin {margin:.0%})"
            )
    if failures:
        print("\ngolden set: REGRESSED\n")
        print("\n".join(failures))
        print(
            "\nRead the matrix above before re-baselining. Reading a wrong answer as "
            "correct and reading a correct one as wrong are not the same event: the "
            "first costs a child a mark and nobody sees it."
        )
        return 1

    print("\ngolden set: ok — within margin of the baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
