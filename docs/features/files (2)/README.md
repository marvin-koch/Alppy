# Feature Documentation

Welcome to the feature documentation hub. This is where every subsystem of the loop is documented with **invariants** (load-bearing rules) to prevent accidental feature removal.

---

## 📁 Directory Structure

```
docs/features/
├─ README.md (this file)
│
├─ sheets/
│  ├─ README.md           # What sheets do, invariants I-sheets-01..10
│  ├─ architecture.md     # Component diagrams, data flows
│  └─ decisions.md        # D1–D5: why each design choice
│
├─ scanning/
│  ├─ README.md           # UID detection, cropping, fiducials
│  ├─ architecture.md     # Scanner pipeline
│  └─ decisions.md        # Why these algorithms
│
├─ grading/
│  ├─ README.md           # Evaluation (auto + human), verdicts
│  ├─ architecture.md     # Grading flow
│  └─ decisions.md        # Why verdict, not heuristic
│
├─ correction/
│  ├─ README.md           # Feedback generation and display
│  ├─ architecture.md     # Feedback pipeline
│  └─ decisions.md        # Why linked to grade
│
├─ adaptation/
│  ├─ README.md           # AI personalization loop
│  ├─ architecture.md     # Difficulty policy, content selection
│  └─ decisions.md        # Why ±1 level, deterministic seeding
│
└─ personalization/
   ├─ README.md           # Per-student customization
   ├─ architecture.md     # Personalization rules
   └─ decisions.md        # Why versioned, why audited
```

---

## 🎯 The Three-Document Rule

Every feature folder has **three documents**:

### 1. README.md (§1 What, §2 Invariants, §3 Module Map)

**What you need to read first:**
- §1: What the feature does (2–3 paragraphs + diagram)
- §2: Invariants table (load-bearing rules for LLMs and reviewers)
- §3: Module map (which files own what)
- §4: How to extend (checklist for developers)
- §5: Privacy & safety constraints
- §6: Test strategy (one test per invariant)

**Time to read:** 10–15 minutes

**Who reads it:** Developers starting work on this feature, LLMs modifying it

### 2. architecture.md (How Components Talk)

**What you need if you're changing the design:**
- Component diagram (boxes and arrows)
- Data flow (input/output classes, transformations)
- Component details (pseudocode for each piece)
- Edge cases (what happens when X, Y, Z)

**Time to read:** 15–20 minutes

**Who reads it:** Architects, LLM agents planning changes

### 3. decisions.md (Why Each Choice Was Made)

**What you need if you're questioning a design:**
- D1, D2, D3… (each design decision with context)
- Alternatives considered (and why they were rejected)
- Tradeoffs (benefits and costs)
- Policy changes (don't do this, here's why)

**Time to read:** 10 minutes per decision

**Who reads it:** Anyone asking "Why is it this way?" or "Can we change this?"

---

## 🔒 The Invariants Pattern (Load-Bearing)

Every feature has a **§2 Invariants table** in its README. These are **not suggestions**—they are *contracts* that code enforces and tests verify.

### Example: I-sheets-01

| # | Invariant | Enforced in | Why it matters | Failure symptom |
|---|---|---|---|---|
| I-sheets-01 | **No AI-generated exercise reaches paper without `approved_at`.** | `render._refuse_unapproved()` | Unreviewed AI reaches children | Safety: incorrect content on paper |

### How to Respect an Invariant (LLM Checklist)

```python
# ✅ SAFE: Code enforces I-sheets-01
if sheet.approved_at is None:
    raise PermissionError("I-sheets-01: Cannot render unapproved sheet")

# ❌ UNSAFE: Invariant ignored
if True:  # Always render, approved or not
    pdf = render_pdf(sheet)
```

### Invariant Symbols in Code

Search for `# I-` to find all enforcements:

```bash
grep -r "# I-" alppy/ tests/
```

Example output:
```
alppy/sheets/render.py:45:    if sheet.approved_at is None:  # I-sheets-01
alppy/sheets/render.py:46:        raise PermissionError("I-sheets-01: Cannot render unapproved sheet")
```

---

## 📋 The 6 Stages of the Loop

Your edtech application is a cycle. Each stage has its own invariants:

### Stage 1: SHEETS (Creation & Rendering)
**Read:** `docs/features/sheets/README.md`  
**Key invariants:**
- I-sheets-01: Unapproved AI blocked
- I-sheets-02: One page = one physical page
- I-sheets-03: Layout version bumped on any coordinate change
- I-sheets-04: Always two PDFs (blank + answer key)
- I-sheets-05: Marks are borders, not backgrounds (printer robustness)

### Stage 2: SCANNING (Detection & Cropping)
**Read:** `docs/features/scanning/README.md`  
**Key invariants:**
- I-scanning-01: UID detected matches layout version
- I-scanning-02: Crop never leaves statement region (privacy)
- I-scanning-03: Fiducials must align with ≤2mm tolerance
- I-scanning-04: Multiple-choice bubbles detected from position

### Stage 3: GRADING (Evaluation)
**Read:** `docs/features/grading/README.md`  
**Key invariants:**
- I-grading-01: Grade issued only on explicit verdict
- I-grading-02: Pending/offline/unreadable = no attempt (not zero)
- I-grading-03: One grade per submission
- I-grading-04: Grading timestamp recorded

### Stage 4: CORRECTION (Feedback)
**Read:** `docs/features/correction/README.md`  
**Key invariants:**
- I-correction-01: Feedback links to grade
- I-correction-02: No feedback without grade
- I-correction-03: Teacher can edit feedback before sending
- I-correction-04: Student name scrubbed from feedback

### Stage 5: ADAPTATION (AI Personalization)
**Read:** `docs/features/adaptation/README.md`  
**Key invariants:**
- I-adaptation-01: New sheet links to previous sheet + student ID
- I-adaptation-02: Difficulty ≤ 1 level per cycle
- I-adaptation-03: AI-generated items approved before rendering
- I-adaptation-04: Deterministic (same input → same output)
- I-adaptation-05: Cannot adapt same student twice in 24h
- I-adaptation-06: Mastery inference uses only attempted items

### Stage 6: PERSONALIZATION (Customization)
**Read:** `docs/features/personalization/README.md`  
**Key invariants:**
- I-personalization-01: Deterministic (same student + sheet → same items)
- I-personalization-02: Rules versioned
- I-personalization-03: Audit trail recorded
- I-personalization-04: Logic is black box (no explanations to student)

---

## 🛠 How to Extend a Feature

### Step 1: Read the README

```bash
cat docs/features/[feature]/README.md
```

Focus on:
- §2: Invariants (are there any your change affects?)
- §3: Module map (which files touch this?)

### Step 2: List Affected Invariants

```
I'm adding a new question type: "drag-and-drop"

This change affects:
- I-sheets-02: Must fit on one page
- I-sheets-05: Mark must be border only
- I-sheets-08: Crop must stay in statement region (if images)
```

### Step 3: Write a Test for Each Invariant

```python
# tests/sheets/test_invariants.py

def test_I_sheets_02_draganddrop_fits_page():
    """I-sheets-02: Drag-and-drop must fit on one page."""
    item = create_draganddrop_item(estimated_height_mm=300)
    with pytest.raises(ItemTooTallError):
        paginate([item])

def test_I_sheets_05_draganddrop_borders():
    """I-sheets-05: Drag-and-drop marks are borders, not backgrounds."""
    html = render_item_html(create_draganddrop_item())
    assert "border:" in html
    assert "background:" not in html
```

### Step 4: Add Invariant Comments to Code

```python
# alppy/sheets/html.py

def render_draganddrop(item: Item) -> str:
    # I-sheets-02: Check height
    assert item.estimated_height_mm <= PAGE_HEIGHT_MM
    
    # I-sheets-05: Draw borders only
    html = render_template('draganddrop.html.j2', item)
    # Note: CSS forces border, no background
    
    # I-sheets-08: Crop will stay in region
    # (because draganddrop items are placed in statement region)
    
    return html
```

### Step 5: Document Your Decision

If you had to make a choice:

```markdown
# docs/features/sheets/decisions.md

## D6: Why drag-and-drop uses border-only styling?

**Date:** 2026-09-15  
**Owner:** [your name]  
**Affected invariant:** I-sheets-05

### Background
[Why you made this choice]

### Considered Alternatives
- A) ...
- B) ✓ [Chosen]

### Tradeoff
- ✅ ...
- ❌ ...
```

---

## ✅ Checklist for Code Review

When reviewing a PR that touches a feature:

- [ ] Which invariants does this PR affect? (List in PR description)
- [ ] Are there tests for each invariant? (Run `pytest tests/ -k test_I_`)
- [ ] Do code comments cite the invariants? (Search for `# I-`)
- [ ] If adding a new rule, is it in §2 of README? (Check for D-number in decisions.md)
- [ ] Did the change respect I-sheets-03? (Check: did layout.py change without version bump?)
- [ ] Privacy check: any student data in wrong place? (Check I-sheets-08, I-correction-04, etc.)

---

## 🚨 Emergency: Bug Found

If you find a bug in a feature:

1. **Document it** in `decisions.md` with a D-number
2. **Add a test** that fails with the bug, passes with the fix
3. **Disable if needed:** Add to `DISABLED_VERSIONS` if it's critical
4. **Audit:** Find which students were affected
5. **Remediate:** Re-render/re-grade/re-adapt as needed

Example:

```markdown
## D7: Bug fix – Layout v2 had incorrect bubble spacing

**Date:** 2026-10-01  
**Owner:** [Scanner team]  
**Issue:** #456  
**Affected invariant:** I-sheets-05

### What went wrong
Bubbles were 1mm too close together; scanner failed on 5% of sheets.

### Fix
Corrected `MC_OPTION_SPACING_MM` in layout.py (requires version bump to v3).

### Impact
- Students from v2 (Sept 2024) need re-scanning with v3 layout
- ~500 sheets affected; re-scanned on 2026-10-05
```

---

## 📚 Reading Guide

### For a Developer Starting on [Feature]
1. Read `docs/features/[feature]/README.md` (15 min)
2. Skim `architecture.md` (5 min)
3. Read the test file `tests/[feature]/test_invariants.py` (5 min)
4. You're ready to code

### For an LLM Extending [Feature]
1. Read `docs/features/[feature]/README.md` (§2 Invariants)
2. List which invariants you touch
3. Read those specific D-numbers in `decisions.md`
4. Write tests before code
5. Cite invariants in comments

### For a Reviewer
1. Check: "Which invariants does this PR affect?"
2. For each invariant, find the code that enforces it
3. Find the test that verifies it
4. Check: "Did the change respect this invariant?"

---

## 🔄 Maintenance Checklist (Every Sprint)

- [ ] Any bugs found? → Add to decisions.md with D-number
- [ ] Any invariants changed? → Update §2 in README.md
- [ ] Any new modules? → Update §3 (module map)
- [ ] Test coverage complete? → Run `pytest tests/ -k test_I_`
- [ ] Any policy changes? → Update policy docs (D-number)

---

## 📞 Quick Links

- **Framework master template:** `docs/FRAMEWORK.md`
- **Running invariant tests:** `pytest tests/ -k test_I_ -v`
- **Finding all invariant enforcements:** `grep -r "# I-" alppy/ tests/`
- **Emergency procedures:** See each feature's README §7

---

## Next Steps

1. **Read a feature:** Pick one (e.g., `docs/features/sheets/README.md`)
2. **Run the tests:** `pytest tests/sheets/test_invariants.py -v`
3. **Make a change:** Add a comment, run tests, submit PR
4. **Document it:** Add a D-number if it's a decision

---

**Last updated:** 2026-09-09

