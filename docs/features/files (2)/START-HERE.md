# 🚀 START HERE: Documentation for Your EdTech Loop

Your edtech application has been documented to prevent accidental feature removal by LLMs and protect your core innovations.

---

## 📁 What You Have

```
docs/
├─ INDEX.md                          # Master index (map to everything)
├─ FRAMEWORK.md                      # Master template (copy for new features)
│
└─ features/                         # Each stage of your loop
   ├─ README.md                      # Hub: overview of all 6 stages
   │
   ├─ sheets/                        # Stage 1: Sheet Creation & Rendering
   │  ├─ README.md                   # ✅ What it does + 10 invariants (COMPLETE)
   │  ├─ architecture.md             # ✅ Component diagrams + code examples (COMPLETE)
   │  └─ decisions.md                # ✅ D1–D5: why each design choice (COMPLETE)
   │
   ├─ scanning/                      # Stage 2: Scanning & Detection
   │  ├─ README.md                   # 📝 Template (fill in your specifics)
   │  ├─ architecture.md             # TODO
   │  └─ decisions.md                # TODO
   │
   ├─ grading/                       # Stage 3: Grading & Evaluation
   │  ├─ README.md                   # 📝 Template
   │  ├─ architecture.md             # TODO
   │  └─ decisions.md                # TODO
   │
   ├─ correction/                    # Stage 4: Feedback & Correction
   │  ├─ README.md                   # 📝 Template
   │  ├─ architecture.md             # TODO
   │  └─ decisions.md                # TODO
   │
   ├─ adaptation/                    # Stage 5: AI Personalization Loop
   │  ├─ README.md                   # 📝 Template + full example
   │  ├─ architecture.md             # TODO (see /ADAPTATION-example.md for full version)
   │  └─ decisions.md                # TODO
   │
   └─ personalization/               # Stage 6: Per-Student Customization
      ├─ README.md                   # 📝 Template
      ├─ architecture.md             # TODO
      └─ decisions.md                # TODO
```

---

## 🎯 5-Minute Quick Start

### 1. Understand the Framework

```bash
# Read this first (15 minutes)
cat docs/INDEX.md
```

This file maps everything. It's your navigation.

### 2. See a Complete Example

```bash
# Read the full sheets feature (30 minutes)
cat docs/features/sheets/README.md
cat docs/features/sheets/architecture.md
cat docs/features/sheets/decisions.md
```

This shows you exactly what a finished feature looks like.

### 3. Understand the Invariants Pattern

The core principle: **§2 Invariants tables** are load-bearing rules.

**Example from sheets:**

| Invariant | Enforced in | Failure |
|---|---|---|
| I-sheets-01 | Unapproved AI blocked at render time | Safety: unreviewed content reaches students |
| I-sheets-03 | Layout version bumped on any coordinate change | Data loss: old scans misalign |
| I-sheets-08 | Crop never leaves statement region | Privacy leak: student ID sent to model |

**Why this matters:** An LLM cannot violate these without failing tests.

### 4. Run the Tests

```bash
# See invariant tests in action
pytest tests/sheets/test_invariants.py -v

# Run ALL invariant tests
pytest tests/ -k test_I_ -v
```

Each invariant has a test. Tests enforce the rules.

### 5. You're Ready

You can now:
- Extend any feature safely
- Review PRs that touch invariants
- Add new features using the same pattern

---

## 📚 Reading by Role

### I'm a Developer

**Time: 20 minutes**

1. Read: `docs/features/[feature]/README.md`
   - §1: What it does
   - §2: Invariants (load-bearing rules)
   - §3: Module map (which files own what)

2. Look at: `tests/[feature]/test_invariants.py`
   - See how each invariant is tested

3. Code with invariant comments: `# I-sheets-01`

### I'm an LLM

**Time: 30 minutes**

1. Read: `docs/features/[feature]/README.md` §2 (Invariants)
2. For each invariant you touch:
   - Read why it exists: `docs/features/[feature]/decisions.md`
   - Find the code: `grep -r "# I-sheets-01" alppy/`
   - Find the test: `pytest tests/ -k test_I_sheets_01 -v`
3. Write tests first
4. Add invariant comments to code
5. Cite in PR: "This respects I-sheets-01 because…"

### I'm a Code Reviewer

**Time: 15 minutes**

1. Check PR description: "Which invariants does this touch?"
2. For each invariant:
   - Find enforcement: `grep -A5 "# I-sheets-01"`
   - Find test: `pytest tests/sheets/test_invariants.py::test_I_sheets_01 -v`
   - Verify the code respects it
3. Run: `pytest tests/ -k test_I_ -v`

### I'm Curious About a Design Choice

**Time: 5 minutes**

Read: `docs/features/[feature]/decisions.md`

Example: **D1: Why do we bump layout version on ANY coordinate change?**

```markdown
## D1: Why layout version bumps on any change

Background: Old sheets from last term are being scanned. If we change a 
coordinate without signalling it, the detector aligns old sheets to the 
new coordinates and gets everything wrong.

Considered alternatives:
- A) Auto-detect layout at scan time (rejected: too complex)
- B) Teachers handle it (rejected: data loss)
- C) ✓ Bump version always (chosen: simple, audit trail clear)

Tradeoff:
- ✅ Old sheets can be re-scanned correctly
- ✅ Clear audit trail
- ❌ Storage keys grow over time (not a burden)
```

---

## 🔒 How This Prevents Feature Removal

### Scenario: LLM wants to remove "unapproved content check"

```python
# LLM reads README.md §2
# Sees: I-sheets-01 "No AI-generated exercise reaches paper without approved_at"

# LLM looks for enforcement
grep -r "# I-sheets-01" alppy/

# Finds:
# alppy/sheets/render.py:45: if sheet.approved_at is None:  # I-sheets-01
#                                  raise PermissionError(...)

# LLM looks for test
pytest tests/ -k test_I_sheets_01 -v

# Finds:
# test_I_sheets_01_unapproved_rejected PASSED
# def test_I_sheets_01_unapproved_rejected():
#     sheet = create_sheet(approved_at=None)
#     with pytest.raises(PermissionError):
#         render_sheet_pdf(sheet)

# LLM realizes: "If I remove this check, the test fails"
# LLM checks decisions.md D1
# LLM sees: "Unreviewed AI content is handed to children" (business impact)
# LLM decides: "I won't remove this"
```

**This is the barrier.** Every invariant has:
1. ✅ Enforcement in code (`# I-`)
2. ✅ Test that verifies it
3. ✅ Decision log explaining why

---

## 📋 The 30+ Invariants (All Stages)

### Stage 1: SHEETS (10 invariants)
- I-sheets-01: Unapproved AI blocked
- I-sheets-02: One page = one physical page
- I-sheets-03: Layout version bumped on any change
- I-sheets-04: Always two PDFs (blank + answer key)
- I-sheets-05: Marks are borders, not backgrounds
- I-sheets-06: Item index resets per page
- I-sheets-07: Answer boxes from placements (final)
- I-sheets-08: Crop stays in statement region (privacy)
- I-sheets-09: Student text readable (≥1.125rem)
- I-sheets-10: Deterministic rendering

### Stages 2–6: Similar depth
- Scanning: 6 invariants (UID, fiducials, privacy)
- Grading: 4 invariants (verdicts, no-zero rule)
- Correction: 4 invariants (links to grade, privacy)
- Adaptation: 6 invariants (difficulty bounds, determinism)
- Personalization: 4 invariants (determinism, audit trail)

**Total: 30+ load-bearing rules** protecting your core features.

---

## ✅ Next Steps

### Phase 1: This Week
- [ ] Read `docs/INDEX.md` (5 min)
- [ ] Read `docs/features/sheets/README.md` (15 min)
- [ ] Run: `pytest tests/sheets/test_invariants.py -v` (2 min)
- [ ] Show your team (10 min meeting)

### Phase 2: This Month
- [ ] Fill in `docs/features/scanning/architecture.md` (2 hours)
- [ ] Fill in `docs/features/grading/decisions.md` (2 hours)
- [ ] Do the same for all 6 stages
- [ ] Add PR template: "Which invariants does this touch?"

### Phase 3: Ongoing
- [ ] Before every merge: `pytest tests/ -k test_I_ -v`
- [ ] Every design decision: Add D-number to decisions.md
- [ ] Every bug: Document in decisions.md
- [ ] Monthly: Update INDEX.md status

---

## 🚨 If You Find a Bug

1. **Add to decisions.md with D-number:**
   ```markdown
   ## D7: Bug fix – Layout v2 spacing

   **Date:** 2026-10-01
   **Issue:** #456 – Bubbles too close, scanner failed
   **Fix:** Corrected MC_OPTION_SPACING_MM (requires layout version bump to v3)
   **Impact:** 500 sheets from Sept 2024 need re-scanning
   ```

2. **Add test that fails with bug, passes with fix:**
   ```python
   def test_I_sheets_05_bubble_spacing_v3():
       """I-sheets-05 (v3): Bubbles properly spaced."""
       # Spacing should be 6mm
       assert MC_OPTION_SPACING_MM >= 6.0
   ```

3. **If critical, disable:**
   ```python
   DISABLED_LAYOUT_VERSIONS = [2]  # v2 had bubble spacing bug
   ```

---

## 📞 Questions?

### "How do I understand invariant I-sheets-03?"
→ Read `docs/features/sheets/decisions.md` D1

### "Can I change the adaptation cooldown from 24h to 12h?"
→ Read `docs/features/adaptation/decisions.md`  
→ Check: Does this violate I-adaptation-05?

### "I want to add a new question type"
→ Read `docs/features/sheets/README.md` §4 (How to extend)  
→ Check which invariants it touches

### "An LLM is modifying this; how do I review it?"
→ Read `docs/INDEX.md` "How to Review as a Code Reviewer"  
→ Run: `pytest tests/ -k test_I_ -v`

---

## 📄 File Quick Links

| File | Purpose | Read time |
|---|---|---|
| `docs/INDEX.md` | Map to everything | 5 min |
| `docs/FRAMEWORK.md` | Template for new features | 15 min |
| `docs/features/README.md` | Hub; the 6 stages | 10 min |
| `docs/features/sheets/README.md` | Invariants I-sheets-01..10 | 15 min |
| `docs/features/sheets/architecture.md` | Component diagrams | 20 min |
| `docs/features/sheets/decisions.md` | D1–D5 rationale | 10 min |
| `docs/features/[stage]/README.md` | Template for each stage | 10 min |

---

## 💡 The Core Idea

Your edtech loop is a cycle:

```
Sheet → Scan → Grade → Correct → Adapt → Personalize → (new Sheet)
```

Each stage has **3–6 invariants** (load-bearing rules).

**Why invariants?**
- They're the contract between you and future developers (including LLMs)
- Tests enforce them automatically
- Decisions log explains why they matter
- Code comments cite them so reviewers can find them

**Result:** When an LLM wants to change something, it hits the invariant tests first. If it wants to break them, it has to read the decision log first. And by then, it understands why they exist.

---

## 🎓 Teaching Others

To teach your team (or train an LLM), use this sequence:

1. **Show:** One complete feature (sheets)
   ```bash
   cat docs/features/sheets/README.md
   ```

2. **Explain:** The invariants pattern
   ```
   "Every rule in §2 has 3 things:
   1. Enforcement in code (# I-sheets-01)
   2. A test (test_I_sheets_01_*)
   3. A decision explaining why (D1, D2…)"
   ```

3. **Do:** Change something small
   ```bash
   # Edit a comment in sheets/render.py
   # Add # I-sheets-01 next to approval check
   # Run tests: pytest tests/ -k test_I_sheets_01
   # Pass? Great. You understand the pattern.
   ```

4. **Extend:** Apply to a new feature
   ```bash
   # Copy docs/features/sheets/ to docs/features/[new-feature]/
   # Fill in §1–3 with your specifics
   # Add invariants
   # Write tests
   # Document decisions
   ```

---

**You're ready. Start with `docs/INDEX.md`. Go.**

