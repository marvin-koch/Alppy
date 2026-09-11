# Deploy

> **Draft.** Nothing has been deployed. Every command below assumes the
> infrastructure in [`../deploy-api.md`](../deploy-api.md), which is itself a
> draft and is not provisioned.

## Before

- [ ] CI is green on the commit being deployed. Not "green on main" — on the
      commit.
- [ ] It is inside the deploy window ([support-model](support-model.md)).
- [ ] If the release contains a migration, you have read
      [rollback](rollback.md) §2 and know which of the two shapes it is.
- [ ] You know who to tell if it goes wrong.

## The web app

Already codified: pushing to `main` runs `deploy-web.yml`. See
[`../deploy-cloudflare.md`](../deploy-cloudflare.md).

## The API and the worker

```bash
git log --oneline -1                      # the commit you are about to ship
fly deploy -c infra/fly/fly.toml --image-label "v$(date +%Y%m%d-%H%M)"
```

The image label is not decoration: it is what [rollback](rollback.md) needs, and
a deploy without one can be rolled back only to "the previous machine image",
which is not a thing you can name in a hurry.

`fly deploy` runs `release_command` — `alembic upgrade head` — on a single
machine first, and stops if it fails. So a failed migration is a failed deploy
with nothing new serving, rather than a crash loop. That is the whole reason the
migration is not in the container's start.

## After — in this order, and do not skip the last one

```bash
fly status -a alppy                                   # both process groups
curl -fsS https://api.alppy.ch/api/v1/health          # ok, not degraded
curl -fsS -H "X-Alppy-Health-Token: $TOKEN" \
     https://api.alppy.ch/api/v1/health/detail        # which dependency, if degraded
fly logs -a alppy | grep -E "worker.startup|cron.start"
```

That last line is the one people skip. The worker is where the scan pipeline,
every render and every retention sweep happen; the API can be perfectly healthy
with no worker at all, and the symptom is a teacher uploading a pile that never
finishes. `cron.start` is the only external evidence that the retention windows
are being enforced.

Then, by hand: sign in, open a class, open one pupil. It takes forty seconds and
it is the only check that exercises the session cookie, the tenant binding and a
real query together.

## If it went wrong

→ [rollback](rollback.md). Do not debug forward on a deployment teachers are
using during a lesson.
