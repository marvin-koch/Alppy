# Roll back

> **Draft.** The policy below is decided. The commands are untested.

## 1 · The policy, decided

**The application rolls back. The database rolls forward.** Two different
things, and conflating them is how a rollback becomes a data-loss incident.

* **Application** — redeploy the previous image tag. Cheap, fast, safe.
* **Database** — **never run `alembic downgrade` on a production database.**
  Several migrations are irreversible in substance: `0041_anonymise_names`
  says so in its own docstring. A `downgrade()` that restores a *column* does
  not restore what was in it. Fix forward: write a new migration.

**Consequence, and it is a rule rather than a preference:**

> A release containing a destructive or irreversible migration **must say so**,
> and **cannot be rolled back** once deployed.

**And this is enforced, not remembered.** A migration that drops a column or a
table, or renames one in place, must carry a module-level `DESTRUCTIVE = True`
with the reason beside it. `scripts/check-migration-safety.py` is a gating CI
job: it parses `upgrade()` and fails the build on a migration that is one-way
and does not say so. Five migrations carry the declaration today — `0019`,
`0021` and `0028` rename in place, `0046` and `0047` drop a column.

`drop_constraint` is deliberately **not** on the list: it loses no rows and is
usually how a key gets widened. A gate that fires mostly on safe things is a
gate whose declaration gets pasted in without being read.

Which means such a release is deployed deliberately, in its own deploy, never
bundled with a feature — because bundling removes the ability to roll back the
feature.

## 2 · Which shape is this release?

| Shape | Rollback |
|---|---|
| No migration | Redeploy the previous image. Done. |
| Additive migration (new nullable column, new table, new index) | Redeploy the previous image. The new schema is harmless to the old code. |
| **Rename or drop** | **Not rollback-able.** Four migrations rename columns in place (`0019`, `0021`, `0028`); old and new application versions cannot share that schema. Fix forward. |
| Data migration | Depends. If it computed something new, additive. If it overwrote, irreversible. |

A rename that has to happen is done in **two releases**: add the new column and
write both, deploy, backfill, then stop writing the old one and drop it in a
later release. Each half is individually rollback-able. That is more work and it
is the difference between a bad afternoon and a lost term.

## 3 · Doing it

```bash
fly releases -a alppy                     # find the last known-good label
fly deploy -a alppy --image registry.fly.io/alppy:<previous-label>
```

Then the same checks as [deploy](deploy.md) §After.

**The migration from the failed release stays applied.** That is correct and
intended: the old code has to tolerate the new schema, which is exactly what the
additive rule buys.

## 4 · Rolling back the web app

`deploy-web.yml` deploys on push to `main`. To roll back: revert the commit and
let it deploy, or `wrangler rollback` from the Cloudflare dashboard. The web app
holds no state, so this is always safe.

## 5 · What is NOT rollback

- A stuck grading pile → [stuck-grading-batch](stuck-grading-batch.md)
- A worker that died → [drain-workers](drain-workers.md)
- One school's data corrupted by a bug → a fix-forward migration, scoped to
  that school; **not** a restore, which would roll back every other school too
