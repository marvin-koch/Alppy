# Support model and deploy window

> **Draft. The commitments are blank, deliberately.** What a school is promised
> is a business decision, and a plausible default written here would be quoted
> back as though it had been agreed.

## Why this is not a normal SaaS question

Failures here cluster between **08:00 and 17:00, Monday to Friday**, and a
failure during a lesson is unrecoverable *for that lesson*. A teacher with
twenty-four pupils and a printed sheet cannot wait for a fix; they teach the
lesson another way and the tool has cost them rather than saved them. That is
the thing that loses a school, and it is not measured by uptime.

The corollary is that **the cheapest reliability win is not deploying during a
lesson.**

## Fill in

| # | Question | Value |
|---|---|---|
| 1 | Response time during school hours on a school day | _______ |
| 2 | Response time outside them | _______ |
| 3 | Is there an out-of-hours contact at all? | _______ |
| 4 | How does a teacher reach support — and is it Alppy or the school's own IT first? | _______ |
| 5 | Who is the named contact at each school? | per establishment |
| 6 | What happens when the one person who knows this system is on holiday? | _______ |

Question 6 is the one that actually matters and the one most likely to be
skipped. Today the answer is "nothing happens", and these documents exist partly
so that it need not stay that way.

## The deploy window — proposed

**Do not deploy during school hours on a school day.** 07:30–17:00 Monday to
Friday, Swiss school terms.

Not a rule about risk appetite; a rule about *when the cost of being wrong is
paid*. The same broken deploy at 18:00 costs an evening of someone's attention
and at 09:20 costs a lesson that cannot be re-run.

Suggested: **16:30 or later**, and not on a Friday unless somebody is available
on Saturday.

Exception: a security fix, and anything in
[`../data-protection/breach-procedure.md`](../data-protection/breach-procedure.md)
§2. Containment does not wait for a window.

### Enforcing it

`deploy-web.yml` fires on every push to `main`, with no window and no gate. Two
options, neither implemented:

* Declare a `production` environment with a **required reviewer**, which the
  workflow already references — a second pair of eyes and a human pause.
* A scheduled deploy rather than a push-triggered one.

Question 7: **who may deploy, and do you want a second reviewer?** Today it is
one person, auditable only through git history.

## Status page

There is none, and a teacher who cannot reach the app has no way to tell an
outage from their own school wifi. That distinction is worth more here than it
sounds: the wrong guess wastes a lesson either way.
