# Onboarding an establishment — pre-launch checklist

This is the artefact that ties the paperwork to the technical steps, and it
should exist before the **first** establishment rather than be improvised for
it. It is a draft: several lines below cannot be ticked today, and saying which
is the point of the document.

## A · Before you talk to a school

Once, not per school.

- [ ] **Backups exist and a restore has been run.** Not "backups are
      configured" — run [restore-from-backup](restore-from-backup.md) §2 and
      write the measured time into §3. *(Blocked: no backups.)*
- [ ] **A staging environment exists**, with its own database, bucket and key.
      *(Drafted in `infra/fly/fly.staging.toml`; not provisioned.)*
- [ ] **The print → scan → grade loop has been run on real paper.** Printed,
      filled in by hand, photographed with a phone, uploaded. *(Never done.
      This is the single most load-bearing pre-launch task and no test can
      substitute for it.)*
- [ ] Error tracking is switched on. *(Wired and inert; needs a vendor.)*
- [ ] [`support-model.md`](support-model.md) has its blanks filled in.
- [ ] [`../data-protection/breach-procedure.md`](../data-protection/breach-procedure.md)
      §0 has its blanks filled in.
- [ ] The privacy notice exists, in the school's voice. *(Not drafted, and not
      engineering's to draft.)*
- [ ] If any model provider is switched on: a DPA is signed and
      [`../data-protection/subprocessors.md`](../data-protection/subprocessors.md)
      §4 is satisfied. **Otherwise leave `ALPPY_AI_CHAT_PROVIDER=echo`** — that
      is a real product, and it is what makes "no transfer until the paperwork
      is done" a position you can hold.

## B · Paperwork, per school

- [ ] Contract, naming the school as controller and Alppy as processor.
- [ ] The subprocessor table handed over, and dated.
- [ ] Retention windows stated in the school's own terms: **scan images 400
      days**, read audit 365 days. If the canton wants shorter, it is
      `ALPPY_SCAN_IMAGE_RETENTION_DAYS` — but note it is **one number for the
      whole deployment**, so a second school with a different window is a
      schema change, not a setting.
- [ ] A DPIA, if the school's DPO requires one. The outline and the facts are
      in [`../data-protection/dpia-outline.md`](../data-protection/dpia-outline.md).
- [ ] Named contact for a breach, with an out-of-hours route.
- [ ] The exit commitment agreed: what happens to their data if Alppy stops
      operating. **Note that the class- and school-level export
      `privacy.md` §4 promises does not exist** — only per-student export does.
      Do not promise it until it is built.

## C · Technical setup

- [ ] School row created. `School.default_curriculum` decides which competency a
      chapter is filed under **per school**, which is what lets Sion and Chur
      share one chapter — get it right at creation.
- [ ] Teacher accounts created. **Manual database work today:** there is no
      endpoint that creates a teacher, resets a password or revokes access. This
      is the first thing an establishment will need and it does not exist. The
      only account-creating command is `alppy.cli seed`, which creates the
      *demo* teacher — do not run it against a real deployment.
- [ ] Classes and roster imported. `class_student` is an interval: a pupil who
      leaves is an `UPDATE`, never a `DELETE`.
- [ ] Subjects and the teaching assignment (`class_teacher_subject`) set.
- [ ] Spend caps reviewed: `ALPPY_AI_DAILY_CAP_CHF` is per school, and the
      shipped 20/day leaves room for one textbook ingest.

## D · Before the first lesson

- [ ] A teacher from the school signs in on **their own laptop and their own
      phone**. The product is used on both.
- [ ] They print one real sheet on the **school's own printer**. Scale, margins
      and toner all matter: the detector reads geometry, and a printer set to
      "fit to page" shifts every fiducial.
- [ ] That sheet is filled in by a real pupil and scanned on the school's own
      copier or a phone. **This is the step that catches what nothing else
      catches.**
- [ ] Check the readings with them. The confidence distribution for that school
      is now a number you have (`python -m alppy.cli health-signals`), and the
      first week of it is the baseline everything later is compared against.
- [ ] Tell them what happens when Alppy is unsure: a low-confidence reading
      **blocks confirmation** until they open it, and reviewing is not
      disagreeing — agreeing is re-sending the same reading.
- [ ] Tell them what happens to written answers if no grader is configured: no
      attempt, counted as *skipped*, **never a zero**.

## E · The first fortnight

- [ ] Read `health_signal.*` weekly. An override rate that is high for this
      school and not for others is their printer, copier or lighting, not the
      product.
- [ ] Watch `scan.page.registration_failed`. Above one page in twenty means
      something physical has changed.
- [ ] Ask the teacher what they did by hand that they expected not to. That is
      where the next thing to build is, and it will not arrive as a bug report.
