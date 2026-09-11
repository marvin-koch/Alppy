# A stuck grading batch

**Usable**, and mostly it now unsticks itself.

## What a teacher reports

"I uploaded the copies and it is still loading." Or: "it will not let me
confirm." Those are different problems with the same appearance.

## 1 · Is it actually stuck?

`reap-jobs` runs **every five minutes**, and a job is only considered stale
after `ALPPY_JOB_STALE_AFTER_S` — 1200 seconds, twice the job timeout, so a
slow-but-alive job is never reaped out from under itself.

**So the first question is not "what is wrong" but "how long has it been".**
Under twenty minutes, a pile that looks stuck may simply be waiting for the next
scheduled reap, and the honest answer to the teacher is "give it until quarter
past". Distinguishing those two is the whole point of this page.

```sql
select id, kind, status, progress, updated_at,
       now() - updated_at as silent_for
from job
where status = 'RUNNING'
order by updated_at;
```

| `silent_for` | Meaning |
|---|---|
| under 10 min | Working. A class set of written answers is legitimately slow — one provider call per crop, strictly sequential. |
| 10–20 min | Probably dead, not yet reapable. Wait, or reap by hand (§2). |
| over 20 min | The reaper should have taken it. If it has not, **the worker is down** → [drain-workers](drain-workers.md). |

That last row is the useful one: a stale `RUNNING` row *older than the reap
window* is not evidence of a stuck job. It is evidence that nothing is running
the reaper.

## 2 · Unstick it by hand

```bash
fly ssh console -a alppy -C "python -m alppy.cli reap-jobs --dry-run"   # look
fly ssh console -a alppy -C "python -m alppy.cli reap-jobs"             # do
```

Idempotent, and it is exactly what the schedule runs. It marks each stale job
`FAILED` with a code from the closed set — never prose, because `Job.error`
crosses to a browser that is regularly projected onto a classroom wall.

The teacher can then re-upload, or re-run grading on the pile.

## 3 · "It will not let me confirm"

A different problem, and usually not a bug.

Two things refuse a confirmation on purpose:

* **Written answers still being read.** `scan_open_grading_pending`. Real work
  in progress — §1.
* **Low-confidence readings nobody has opened.** `scan_low_confidence_unreviewed`.
  The refusal names the specific `detection_ids` rather than a count, because
  the teacher has to go and open rows. **Reviewing is not disagreeing**: a
  teacher who looks and agrees affirms by re-sending the same reading, so this
  is a few taps and not a re-marking exercise. It exists because confirming a
  pile without opening it used to turn every unsure reading into a mark.

Neither is unstuck by reaping anything.

## 4 · Grading finished but produced nothing

Expected, and correct, in three cases. A written answer with no verdict produces
**no attempt** and is counted as *skipped*, never a zero:

* the vision grader is offline (`ALPPY_AI_CHAT_PROVIDER=echo` — the default)
* the crop was unreadable
* the model returned no verdict

Check which:

```sql
select outcome, count(*) from detection
where scan_page_id in (select id from scan_page where scan_id = '<id>')
group by outcome;
```

`NOT_GRADEABLE` in quantity with an offline provider is the system working as
configured, not a fault. The teacher marks those by hand.

## 5 · The whole class failed, not one pile

Then it is not a stuck job.

```bash
fly logs -a alppy | grep -E "ai.call.failed|ai.budget.exceeded|job.reap"
```

* `ai.budget.exceeded` — the school hit its spend ceiling. Raise
  `ALPPY_AI_DAILY_CAP_CHF`, or wait for the rolling window.
* `ai.call.failed` in volume — the provider is having a bad day. Batched
  generation already isolates a content failure per plan and retries a
  whole-call failure once, split into single-plan calls, so a partial pile is
  expected and a total one means the provider, not us.
* Nothing at all — the worker is down → [drain-workers](drain-workers.md).
