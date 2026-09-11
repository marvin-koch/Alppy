# Data protection

`docs/privacy.md` §6 has always stated, in its own words, that none of the
required data-protection paperwork exists. This directory does not change that.
What it does is separate the documents engineering **can** usefully produce from
the ones it should not touch, so what remains is a shorter and clearer list.

## Ready for non-engineering review

| Document | What it is |
|---|---|
| [`subprocessors.md`](subprocessors.md) | A maintained table of who processes what, where, and under what safeguard. Complete and current; the artefact a cantonal IT department asks for first. |
| [`dpia-outline.md`](dpia-outline.md) | The structure of a DPIA with §§1–5 and §8's technical half **filled in from the code**, and the risk assessment and legal conclusions **deliberately empty**. |
| [`breach-procedure.md`](breach-procedure.md) | The order of operations, which is engineering's to state, with every name and timeline left as a blank. |

## Not drafted here, and deliberately

These carry legal weight. A structural skeleton is fine; filling in commitments
on the business's behalf is not, because a plausible draft gets signed.

| Document | Who | Why not here |
|---|---|---|
| **DPA with a model vendor** | Counsel | It is a contract. There is also nothing to sign yet: the shipped default provider is offline and no transfer is active. |
| **Processing register** (nLPD art. 12) | The controller | The controller is the school, and the register is theirs. §§2–5 of the DPIA outline are the inputs. |
| **Privacy notice** for parents and teachers | The school, with counsel | It is a statement to data subjects, in the school's voice, about its own processing. |
| **The DPIA itself** | Counsel / DPO | See the outline. |

## The one thing engineering should say out loud

**In the shipped configuration, no personal data leaves the deployment.** The
default AI provider is offline (`echo`); written answers are counted as skipped
rather than graded, and MCQ and true/false grading is unaffected. That is a real
product, and it means "no transfer until there is a DPA" is a position that can
be held while the paperwork is done rather than a reason to wait.
