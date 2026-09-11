# Breach notification — procedure skeleton

> **A skeleton, not a procedure.** The *shape* below is engineering's to
> propose; the **named people, the committed timelines and the decision about
> whether a given incident is notifiable are not**, and are deliberately left as
> blanks rather than filled in with plausible defaults. A procedure naming
> nobody is obviously incomplete. A procedure naming the wrong person reads as
> complete and fails at 08:00 on a Tuesday.

Under the revised Swiss FADP (nLPD art. 24), the **controller** notifies the
FDPIC **as soon as possible** where a breach is likely to result in a high risk
to the data subject. As **processor**, Alppy's duty runs to the controller — the
school — and it is immediate. That direction matters: Alppy does not decide
whether the FDPIC is notified; the school does, and cannot do so before Alppy
has told them.

---

## 0 · Fill these in before this document is worth anything

| # | Blank | Who decides |
|---|---|---|
| 1 | Who is on call, and how they are reached out of hours | You |
| 2 | The committed time from detection to notifying a school | You — see [`support-model.md`](../runbook/support-model.md) |
| 3 | Who at each school is the named contact | Per establishment, at onboarding |
| 4 | Who may speak to a parent, and who may not | You |
| 5 | Who decides whether an incident is notifiable | The school, on advice — but somebody has to ask them |
| 6 | Which counsel is called, and at what hour | You |

---

## 1 · What counts as a breach here

Not an outage. A breach is unauthorised access to, loss of, or alteration of
personal data. In this system, concretely:

| Kind | Example | Severity |
|---|---|---|
| **Cross-tenant read** | A teacher sees another school's roster | High — this is what two layers of tenancy exist to prevent |
| **Handwriting exposure** | Scan images or crops reachable without a session; a presigned URL leaked and still valid | High — minors, special-category-adjacent |
| **Name to a provider** | The PII gate bypassed or a name inside an answer box | High |
| **Credential loss** | `ALPPY_SECRET_KEY`, a database password, an S3 key | High — the signing key forges any session |
| **Roster loss** | A volume destroyed with no backup | High, and today **unrecoverable** |
| **Audit loss** | `AccessLog` destroyed | Medium — it is the record of who read what |

An outage with no data consequence is an incident, not a breach. It goes to the
runbook, not here.

---

## 2 · Order of operations

The order is the part that is genuinely engineering's to state, because it is
about what this system can do.

1. **Contain.** Do not investigate first.
   * Leaked signing key → set a new `ALPPY_SECRET_KEY` with the old one in
     `ALPPY_SECRET_KEY_FALLBACKS`, deploy, then **remove the fallback
     immediately** rather than waiting out the session lifetime. That is the one
     case where ejecting every teacher mid-lesson is the correct trade.
     ([`rotate-a-secret.md`](../runbook/rotate-a-secret.md))
   * Leaked object-store credentials → rotate the key. Presigned URLs already
     issued expire in 120 seconds.
   * Suspected cross-tenant read → the tenancy check is `get_membership` and the
     GUC writer is `db/tenancy.py`. An unbound session sees *nothing*, so the
     failure mode is empty lists, not other people's rows — which is what makes
     "a handler forgot `TenantDep`" the likelier diagnosis.
2. **Preserve evidence.** `AccessLog` answers "who read whose file" and is swept
   at 365 days. `ModelCall` answers "did any of our data reach provider X" and
   is content-free by construction. **Stop the retention sweeps before they
   cross the relevant window** — the worker's cron runs nightly, so this is a
   same-day concern.
3. **Notify the school.** _[within: ______ ]_ Every affected school, not just
   the one that noticed. Say what is known, what is not, and when the next
   update comes. Do not wait for a complete picture; a school cannot start its
   own clock until Alppy has started it.
4. **Assess.** Scope (which schools, which pupils, which data), cause, whether
   the data was actually accessed or merely exposed.
5. **The school decides on the FDPIC.** Alppy supplies the facts. _[who at
   Alppy is available to help them do this: ______ ]_
6. **Inform data subjects** where required. This is the school's act, through
   its existing relationship with parents. Alppy does not contact parents.
   _[who may speak to a parent if asked directly: ______ ]_
7. **Write it down.** What happened, when each step occurred, what was decided
   and by whom. Independently of whether the FDPIC was notified.
8. **Fix, and add the test.** The fix is not finished until something would
   catch a recurrence.

---

## 3 · What Alppy can actually tell a school

Worth knowing before the phone call, because "we don't know" is the answer that
ends a procurement:

| Question | Can it be answered? | From |
|---|---|---|
| Did any of our data go to provider X? | **Yes** | `ModelCall` — that is what it is for |
| What exactly was sent? | Only if that school enabled the prompt log | `PromptLog`, off by default |
| Who read my child's file? | **Yes**, for 365 days | `AccessLog` |
| Were the scan images exposed? | Partly — object access is not logged | — |
| Can you restore to before the incident? | **No.** There are no backups | — |
| Which pupils were affected? | Yes, where the incident is scoped to rows | The tenant columns |

Rows four and five are gaps. Both are named in
[`../deploy-api.md`](../deploy-api.md) §6.
