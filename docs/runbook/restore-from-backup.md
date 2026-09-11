# Restore from backup

> ## ⚠ There are no backups.
>
> Not of the database, not of the object store. No configuration, no script, no
> schedule, no tested restore. **A volume loss today is total and permanent loss
> of a term's graded work**, and there is no RPO and no RTO because there is
> nothing to measure.
>
> This document is written in advance so that the day backups exist, the
> procedure does too. Until then it describes something that cannot be done.

## 0 · What has to happen first **[you]**

1. Provision a managed Postgres with automated backups and point-in-time
   recovery. `fly postgres create` gives daily snapshots; PITR is worth the
   difference, because "restore to yesterday" loses a day of grading and
   "restore to 14:05" loses five minutes.
2. **Decide the retention window.** The default position taken in this
   repository is **30 days**, with the consequence written down in §4 rather
   than discovered later.
3. Back up the object store. It has no backup, no versioning (deliberately
   disabled) and no deletion protection. This is a separate problem from the
   database and is not solved by solving that one.
4. **Run §2 once, for real, and write the measured time into §3.**

## 1 · Decide what you are actually restoring

| Symptom | Is a restore the answer? |
|---|---|
| One school's data corrupted by a bug | **No.** A restore rolls back every other school too. Fix forward, scoped. |
| A teacher deleted a class by mistake | Probably not. `class_student` is an interval and leaving is an `UPDATE`; the rows are likely still there. |
| A pupil erased under a data request | **No.** That was intentional. See §4. |
| The database volume is gone | Yes. |
| A migration destroyed data | Yes — and this is the case the "no downgrade" rule in [rollback](rollback.md) exists to make rarer. |

A restore is the most destructive tool here. Ask the question above before
reaching for it.

## 2 · The procedure

```bash
# 1. STOP writing. A restore under live traffic produces a database that is
#    neither the old state nor the new one.
fly scale count app=0 worker=0 -a alppy

# 2. Restore to a NEW cluster, never over the live one. If the restore is
#    wrong you still have the thing you were trying to fix.
fly postgres create --name alppy-db-restored --fork-from alppy-db --restore-target-time "2026-09-11T14:05:00Z"

# 3. Verify BEFORE cutting over. The counts that matter:
psql "$RESTORED_URL" -c "select count(*) from student;"
psql "$RESTORED_URL" -c "select count(*) from attempt;"
psql "$RESTORED_URL" -c "select max(created_at) from attempt;"   # how much was lost
psql "$RESTORED_URL" -c "select count(*) from person where anonymised_at is not null;"

# 4. Re-apply erasures. READ §4 BEFORE SKIPPING THIS.

# 5. Cut over and bring it back.
fly secrets set ALPPY_DATABASE_URL="..." ALPPY_ADMIN_DATABASE_URL="..." -a alppy
fly scale count app=2 worker=1 -a alppy
```

**The object store is not restored by any of this.** A database restored to
last Tuesday references scan images by key; if the object store also lost data,
those keys point at nothing and the review screen shows empty frames. The grade,
the transcription and the verdict survive on `Detection` regardless — which is
the same property that makes the retention purge safe.

## 3 · Measured recovery time

| Measurement | Value |
|---|---|
| Last drill | **never** |
| Time to restore | **unknown** |
| Data loss at that point | **unknown** |
| Who ran it | — |

> **Fill this in by running §2 against real infrastructure.** An untested
> restore is not meaningfully different from no backup: it is a belief, and the
> moment it is needed is the worst possible moment to find out it was wrong.
> Nobody can do this on your behalf.

## 4 · A restore un-deletes erased pupils

This is the part that is easy to miss and is a data-protection problem rather
than an operational one.

If a pupil was erased on the 3rd and you restore to the 1st, that pupil is back.
Their name, their attempts, their handwriting. The erasure request was honoured
and then quietly undone.

**So the backup window is also the window in which an erasure is not really
complete.** The position taken here is **30 days**, on the basis that it is a
defensible disaster-recovery window and that the gap is closed by procedure
rather than pretended away:

1. Keep an erasure log — pupil id, date, requester — **outside** the database
   being restored.
2. Step 4 of §2 is not optional: after any restore, re-apply every erasure from
   that log that falls between the restore point and now.
3. Tell the school. An erasure that was undone and re-applied is a fact they are
   entitled to.

That log does not exist yet. It is one of the things to build before the first
real establishment.
