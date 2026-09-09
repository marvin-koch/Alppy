# Documentation Index

**Purpose:** Map to all documentation for the edtech loop application  
**Last updated:** 2026-09-09

---

## 📚 Documentation Structure

```
docs/
├─ INDEX.md (this file)           # Map to all documentation
├─ FRAMEWORK.md                   # Master template for all features
│
└─ features/
   ├─ README.md                   # Hub: quick start + the 6 stages
   │
   ├─ sheets/                     # Stage 1: Creation & Rendering
   │  ├─ README.md
   │  ├─ architecture.md
   │  └─ decisions.md
   │
   ├─ scanning/                   # Stage 2: Detection & Cropping
   │  ├─ README.md
   │  ├─ architecture.md (TODO)
   │  └─ decisions.md (TODO)
   │
   ├─ grading/                    # Stage 3: Evaluation
   │  ├─ README.md
   │  ├─ architecture.md (TODO)
   │  └─ decisions.md (TODO)
   │
   ├─ correction/                 # Stage 4: Feedback
   │  ├─ README.md
   │  ├─ architecture.md (TODO)
   │  └─ decisions.md (TODO)
   │
   ├─ adaptation/                 # Stage 5: AI Personalization
   │  ├─ README.md
   │  ├─ architecture.md (TODO)
   │  └─ decisions.md (TODO)
   │
   └─ personalization/            # Stage 6: Customization
      ├─ README.md
      ├─ architecture.md (TODO)
      └─ decisions.md (TODO)
```

---

## 🗺 Reading Guide by Role

### I'm a Developer Starting on [Feature]

1. **Read:** `docs/features/[feature]/README.md`
   - §1: What it does (5 min)
   - §2: Invariants (5 min) ← **This is critical**
   - §3: Module map (2 min)
   - §4: How to extend (2 min)

2. **Look at tests:** `tests/[feature]/test_invariants.py`
   - See which invariants are tested
   - Understand the test patterns (5 min)

3. **You're ready to code.** (Total time: 20 min)

### I'm an LLM Extending [Feature]

1. **Read:** `docs/features/[feature]/README.md` §2 (Invariants)

2. **For each invariant you touch:**
   - Read `docs/features/[feature]/decisions.md` (the D-number explaining why)
   - Look at the code that enforces it (`grep -r "# I-"`)
   - Find the test (`tests/[feature]/test_invariants.py`)

3. **Write tests first**, then code.

4. **Cite invariants in comments:** `# I-sheets-01`

### I'm a Code Reviewer

1. **PR description must list invariants touched:** "This PR affects I-sheets-01, I-sheets-05"

2. **For each invariant:**
   - Find code that enforces it: `grep -A5 "# I-sheets-01"`
   - Find test: `pytest tests/ -k "test_I_sheets_01" -v`
   - Verify: "Does the code respect this invariant?"

3. **Check:** Is test coverage complete?
   ```bash
   pytest tests/ -k test_I_ -v
   ```

### I'm Wondering "Why Is It This Way?"

1. **Read:** `docs/features/[feature]/decisions.md` (D1, D2, D3…)
   - Each decision has a D-number
   - Explains: background, alternatives considered, tradeoff

### I'm Planning the Architecture

1. **Read:** `docs/features/README.md` (the hub)
   - Overview of all 6 stages
   - How they connect

2. **For each stage, read:**
   - `docs/features/[stage]/architecture.md`
   - Component diagrams, data flows, edge cases

---

## 🎯 Quick Links

| What I need | File | Time |
|---|---|---|
| **Quick start** | `docs/features/README.md` | 5 min |
| **Framework template** | `docs/FRAMEWORK.md` | 15 min |
| **One feature's invariants** | `docs/features/[feature]/README.md` §2 | 5 min |
| **One feature's architecture** | `docs/features/[feature]/architecture.md` | 15 min |
| **Why a design choice was made** | `docs/features/[feature]/decisions.md` (D1, D2…) | 3 min per decision |
| **All invariant tests** | `pytest tests/ -k test_I_ -v` | 2 min |
| **Find all invariant enforcements** | `grep -r "# I-" alppy/ tests/` | 1 min |

---

## 📋 The Invariants (All 6 Stages)

### Stage 1: SHEETS (Creation & Rendering)
**Read:** `docs/features/sheets/README.md`

- **I-sheets-01:** Unapproved AI blocked
- **I-sheets-02:** One page = one physical page
- **I-sheets-03:** Layout version bumped on any coordinate change
- **I-sheets-04:** Always two PDFs (blank + answer key)
- **I-sheets-05:** Marks are borders, not backgrounds
- **I-sheets-06:** Item index resets per page
- **I-sheets-07:** Answer boxes from placements, not recomputed
- **I-sheets-08:** Crop never leaves statement region (privacy)
- **I-sheets-09:** Student text ≥ 1.125rem (readable)
- **I-sheets-10:** Deterministic rendering

### Stage 2: SCANNING (Detection & Cropping)
**Read:** `docs/features/scanning/README.md`

- **I-scanning-01:** UID matches layout version
- **I-scanning-02:** Crop stays in statement region (privacy)
- **I-scanning-03:** Fiducials aligned ≤2mm
- **I-scanning-04:** Bubbles detected by position, not color
- **I-scanning-05:** Crop from printed area only
- **I-scanning-06:** Detections ordered by page

### Stage 3: GRADING (Evaluation)
**Read:** `docs/features/grading/README.md`

- **I-grading-01:** Grade issued only on explicit verdict
- **I-grading-02:** Pending/offline = no attempt (not zero)
- **I-grading-03:** One grade per submission
- **I-grading-04:** Grading timestamp recorded

### Stage 4: CORRECTION (Feedback)
**Read:** `docs/features/correction/README.md`

- **I-correction-01:** Feedback links to grade
- **I-correction-02:** No feedback without grade
- **I-correction-03:** Teacher can edit before student sees
- **I-correction-04:** Student name scrubbed from feedback

### Stage 5: ADAPTATION (AI Personalization)
**Read:** `docs/features/adaptation/README.md`

- **I-adaptation-01:** New sheet links to previous + student ID
- **I-adaptation-02:** Difficulty ≤ ±1 level per cycle
- **I-adaptation-03:** AI items approved before rendering
- **I-adaptation-04:** Deterministic seeding
- **I-adaptation-05:** Cannot adapt same student twice in 24h
- **I-adaptation-06:** Mastery from attempted items only

### Stage 6: PERSONALIZATION (Customization)
**Read:** `docs/features/personalization/README.md`

- **I-personalization-01:** Deterministic (same input → same output)
- **I-personalization-02:** Rules versioned
- **I-personalization-03:** Audit trail recorded
- **I-personalization-04:** Logic is black box (no explanations)

---

## ✅ Maintenance Checklist

### When You Find a Bug
1. Document in `docs/features/[feature]/decisions.md` with D-number
2. Add test that fails with bug, passes with fix
3. If critical, add to `DISABLED_VERSIONS` and document

### When You Make a Design Decision
1. Add to `docs/features/[feature]/decisions.md` with D-number
2. Format: Background, Alternatives, Tradeoff, Reinforced Invariant
3. Cite in code: `# D1: Why layout versions...`

### When You Change an Invariant
1. **Stop.** Is this safe?
2. Read `docs/features/[feature]/decisions.md` for context
3. If you must change it:
   - Add new invariant to §2 in README
   - Add D-number explaining why
   - Create test for new rule
   - Update all code enforcement points

### Every Sprint
- [ ] Test coverage: `pytest tests/ -k test_I_ -v`
- [ ] Documentation updated? (`git diff docs/features/`)
- [ ] New invariants documented?
- [ ] Decisions log current?

---

## 🔄 The LLM Extension Workflow

When asking an LLM to modify [Feature]:

```
You are extending the [FEATURE] module.

BEFORE YOU CODE:
1. Read docs/features/[feature]/README.md (§2 Invariants)
2. Read docs/features/[feature]/decisions.md (why each rule exists)
3. List which invariants your change touches
4. Explain why your code does NOT violate them

WHEN YOU CODE:
- Cite invariants: # I-feature-01
- Test first: write test for each invariant
- If adding a rule, update README.md §2 first

BEFORE YOU SUBMIT:
- Run: pytest tests/ -k test_I_ -v
- Explain in PR: "This respects I-feature-XX because…"
```

---

## 📞 Getting Help

### "I don't understand invariant I-sheets-03"
→ Read `docs/features/sheets/decisions.md` D1 (Why layout versions)

### "Can I change the 24-hour adaptation cooldown to 12 hours?"
→ Read `docs/features/adaptation/decisions.md` D3  
→ Check: Does this violate I-adaptation-05?

### "Why do we crop answer boxes at print time, not scan time?"
→ Read `docs/features/sheets/decisions.md` D5

### "I found a bug where sheets misaligned"
→ Check: Was `LAYOUT_VERSION` bumped when `layout.py` changed?  
→ Add to decisions.md with D-number: "Bug fix – Layout v2 misalignment"

---

## 🚀 Next Steps

1. **Read the hub:** `docs/features/README.md` (10 min)
2. **Pick one feature:** Start with sheets (most complete example)
3. **Run invariant tests:**
   ```bash
   pytest tests/sheets/test_invariants.py -v
   ```
4. **Make a small change:** Add a comment to code, cite an invariant, submit PR
5. **Document it:** Add to decisions.md if needed

---

## 📄 File Status

| File | Status | Notes |
|---|---|---|
| `docs/FRAMEWORK.md` | ✅ Complete | Master template for all features |
| `docs/features/README.md` | ✅ Complete | Hub; quick start |
| `docs/features/sheets/README.md` | ✅ Complete | Full example with 10 invariants |
| `docs/features/sheets/architecture.md` | ✅ Complete | Component diagrams, code examples |
| `docs/features/sheets/decisions.md` | ✅ Complete | D1–D5 with rationale |
| `docs/features/scanning/README.md` | ✅ Template | Fill in specifics |
| `docs/features/grading/README.md` | ✅ Template | Fill in specifics |
| `docs/features/correction/README.md` | ✅ Template | Fill in specifics |
| `docs/features/adaptation/README.md` | ✅ Template | Full example in `/ADAPTATION-example.md` |
| `docs/features/personalization/README.md` | ✅ Template | Fill in specifics |

---

**Keep this index updated as you add new features or modify existing ones.**

