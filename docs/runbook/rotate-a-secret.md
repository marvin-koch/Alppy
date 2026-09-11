# Rotate a secret

**Usable.** The code half shipped with the session key ring; this is the
procedure around it.

## The session signing key — the one that used to be an outage

`ALPPY_SECRET_KEY` signs the session cookie. Changing it used to invalidate
every live session at the instant of the deploy: every teacher in every school
logged out mid-lesson, mid-scan, mid-review. A key that can only be rotated by
causing an outage is a key that never gets rotated, which is not the state a
leaked one should find you in.

`ALPPY_SECRET_KEY_FALLBACKS` is a list of retired keys that are still
**accepted** and never used to sign.

### Planned rotation — no outage

```bash
NEW=$(openssl rand -hex 32)
OLD=$(fly secrets list -a alppy >/dev/null; echo "<the current value>")

# 1. New key signs; old key still verifies.
fly secrets set -a alppy \
  ALPPY_SECRET_KEY="$NEW" \
  ALPPY_SECRET_KEY_FALLBACKS="[\"$OLD\"]"

# 2. Wait out ALPPY_SESSION_MAX_AGE_S — 12 hours by default. So: overnight.
#    Every cookie signed with the old key has expired on its own by now.

# 3. Drop the fallback.
fly secrets unset -a alppy ALPPY_SECRET_KEY_FALLBACKS
```

Between steps 1 and 3 both keys verify and only the new one signs. No teacher
notices anything.

### Compromised key — outage on purpose

Skip the waiting. Set the new key with **no fallback**, deploy, and accept that
everyone is logged out: while the old key verifies, anybody holding it can mint
a session for any teacher in any school. That is the one case where ejecting
every teacher mid-lesson is the correct trade, and it should be stated out loud
rather than decided in the moment.

Then: rotate everything else it could have been leaked alongside, and go to
[`../data-protection/breach-procedure.md`](../data-protection/breach-procedure.md).

## The database passwords

Two roles, and they are not interchangeable: `ALPPY_DATABASE_URL` is the
low-privilege role the API connects as, `ALPPY_ADMIN_DATABASE_URL` is the schema
owner. Row-level security does not apply to a table's owner, so pointing both at
the same role switches the whole tenant mechanism off while looking perfectly
healthy. The app refuses to boot on that, which is what stops it happening by
accident.

```sql
ALTER ROLE alppy_app WITH PASSWORD '<new>';
```
```bash
fly secrets set -a alppy ALPPY_DATABASE_URL="postgresql+psycopg://alppy_app:<new>@..."
```

Rotate them separately, and verify after each:

```bash
curl -fsS -H "X-Alppy-Health-Token: $TOKEN" https://api.alppy.ch/api/v1/health/detail
```

Then sign in and open a class. `database: true` only proves a connection was
opened; it does not prove the right role opened it, and the difference between
the two roles is invisible to a health check and visible immediately to a
teacher (an empty roster where rows should be means the tenant binding is
wrong, not that the data is gone).

## The object-store keys

```bash
fly secrets set -a alppy ALPPY_S3_ACCESS_KEY="..." ALPPY_S3_SECRET_KEY="..."
```

Presigned URLs already issued stay valid for their remaining life — 120 seconds.
Nothing needs to be waited for.

## The provider key

`ALPPY_OPENAI_API_KEY` / `ALPPY_ANTHROPIC_API_KEY`. A wrong or missing key does
not fail loudly: the app logs `ai.provider.no_key` and **falls back to `echo`**,
so the symptom is generated content that arrives suspiciously fast and
suspiciously generic. After rotating, check the log rather than the screen.

## The health-detail token

`ALPPY_HEALTH_DETAIL_TOKEN`. Rotate freely; nothing depends on it but you.

## Everything at once

The order is: signing key last. It is the only one whose rotation is visible to
a teacher.
