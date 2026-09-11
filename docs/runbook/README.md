# Runbook

Nothing described how to deploy, roll back, restore, rotate a secret, drain
workers or unstick a batch. The software documentation in this repository is
good; the operational half did not exist at all.

These are written to be followed by somebody who is not the person who built
this, at 08:10 on a Tuesday, with a teacher waiting.

| Procedure | Status |
|---|---|
| [Deploy](deploy.md) | **Draft** — depends on infrastructure that is not provisioned |
| [Roll back](rollback.md) | **Draft**, and the policy in it is decided |
| [Restore from backup](restore-from-backup.md) | **Draft, and untested. There is nothing to restore from.** |
| [Rotate a secret](rotate-a-secret.md) | **Usable** — the code half is shipped |
| [Drain and restart workers](drain-workers.md) | **Usable** |
| [A stuck grading batch](stuck-grading-batch.md) | **Usable** |
| [Support model and deploy window](support-model.md) | **Draft — commitments are blank** |
| [Onboarding an establishment](onboard-an-establishment.md) | **Draft** — the technical steps work; the paperwork lines do not tick yet |

## What must be run by a human before it can be trusted

| Procedure | Why |
|---|---|
| **Restore** | An untested backup procedure is not meaningfully different from no backup. It has to be executed once, against real infrastructure, with the wall-clock time written into the document. Nobody can do this for you. |
| **Deploy** | Every command in it is currently hypothetical. |
| **Rollback** | The forward-only database policy is sound and has never been exercised. |

## The order things break in

Ranked by how likely it is to be what is actually wrong, which is not the same
as how serious it is:

1. A grading pile looks stuck → [stuck-grading-batch](stuck-grading-batch.md)
2. A deploy failed → [rollback](rollback.md)
3. Scans upload but nothing happens → the worker is down →
   [drain-workers](drain-workers.md)
4. Everything is 500 → check `/api/v1/health/detail`, then the database
5. Data is gone → [restore](restore-from-backup.md), and the honest answer
   today is that it is not recoverable
