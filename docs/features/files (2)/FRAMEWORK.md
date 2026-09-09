# EdTech Application Documentation Framework

**Status:** Master template  
**Audience:** Developers, LLM agents, code reviewers  
**Last updated:** 2026-09-09

---

## Overview

This framework ensures that every feature in the edtech loop is documented in a way that is both **human-readable** and **LLM-safe**. It prevents unintended feature removal by establishing load-bearing invariants that must be enforced and tested.

### The Core Principle

Each feature has a **§2 Invariants table**. These are not suggestions—they are *contracts* that code must uphold. An LLM (or developer) cannot break them without failing tests and code review.

---

## Documentation Structure

Every feature lives in `docs/features/[feature-name]/` with three documents:

```
docs/features/[feature-name]/
├─ README.md              # What it does, invariants, module map
├─ architecture.md        # How components talk, Flow diagrams
└─ decisions.md           # Why each design choice was made (D1, D2, etc)
```

### The Three-Document Rule

| Document | Purpose | Audience |
|----------|---------|----------|
| **README.md** | What the feature does, its invariants, which files own what | Developers starting work on this feature |
| **architecture.md** | Flow diagrams, component interaction, data models | Architects, LLM agents planning changes |
| **decisions.md** | Why we made each choice (D1: "Why layout version bumps on change?") | Anyone asking "Why is it this way?" |

**Never skip one.** The triad makes invariants auditable.

---

## The Invariants Pattern (§2)

### Template: Invariants Table

| # | Invariant | Enforced in | Why it matters | Failure symptom |
|---|---|---|---|---|
| I-[feature]-01 | [Rule in plain English] | module/file.py, line X | [business impact] | [what breaks for users] |
| I-[feature]-02 | [Next rule] | ... | ... | ... |

### How to Read an Invariant (for LLMs)

```python
# ✅ SAFE: Respects I-sheets-01
if layout_changed:
    version += 1  # Bump the layout version

# ❌ UNSAFE: Violates I-sheets-01
if minor_adjustment:
    pass  # Just tweak the number, don't bump version
    # LLM-readable reason: I-sheets-01 says changing *any* number is a version bump
```

### Categories of Invariants

| Category | Example | Reason |
|----------|---------|--------|
| **Data integrity** | "Never recompute after the gate closes" | Final data; updates happen upstream |
| **Privacy/Security** | "Student name never reaches model provider" | Compliance, scrubbing at ingest |
| **Feature interaction** | "Two PDFs from one SheetData" | Blank + answer key must sync |
| **Performance** | "Deterministic rendering (no clock in markup)" | Reproducibility for debugging |
| **User safety** | "Item too tall is refused, not clipped" | Silent failures cause unreadable output |

---

## The Loop Structure (Your Architecture)

Document each stage as a **subsystem** with its own invariants:

### Stage 1: SHEETS (Creation & Rendering)
- **Input:** Textbook chapter / AI proposal / teacher's content
- **Output:** `Sheet + SheetItem[] + SheetInstance[]` → blank.pdf + answer-key.pdf
- **Key invariants:** Unapproved AI blocked; layout version bumped; deterministic

### Stage 2: SCANNING (Detection & Cropping)
- **Input:** Phone photo / scan
- **Output:** `Detection[] → Attempt[]`
- **Key invariants:** UID matches layout version; crop stays in statement region (privacy)

### Stage 3: GRADING (Evaluation)
- **Input:** `Attempt[]` from scan
- **Output:** `Grade[] + Verdict[]`
- **Key invariants:** Grade on verdict only (not heuristic); pending/offline = no attempt

### Stage 4: CORRECTION (Feedback)
- **Input:** `Grade[] + Verdict[]`
- **Output:** `Feedback[]` (explanation of correct answer)
- **Key invariants:** Feedback links to grade; no feedback without grade; no student name

### Stage 5: ADAPTATION (AI Personalization)
- **Input:** Student performance `Grade[]`
- **Output:** New personalized `Sheet`
- **Key invariants:** Difficulty ≤ 1 level per cycle; deterministic; AI approved before render

### Stage 6: PERSONALIZATION (Customization)
- **Input:** `Sheet` + student profile
- **Output:** Customized item selection
- **Key invariants:** Deterministic; versioned; audit trail recorded

---

## Template: README.md for a Feature

Save as `docs/features/[feature-name]/README.md`:

```markdown
# [Feature Name] Feature

**Status:** [draft | describes `main` as of DATE]  
**Audience:** developers, LLM agents, reviewers  
**Layout version:** [if applicable, e.g., v1, v2]

## 1 · What it does

[Subsystem's role in the loop. 2–3 paragraphs.]

\`\`\`
[ASCII diagram showing flow]
\`\`\`

### Key Properties
1. [Property 1 and why it matters]
2. [Property 2 and why it matters]
3. [Property 3 and why it matters]

---

## 2 · Invariants (Load-Bearing)

These are rules a reviewer has to enforce by reading. Each names where it is enforced and what breaks when it is not.

| # | Invariant | Enforced in | Why it matters | Failure symptom |
|---|---|---|---|---|
| I-[feature]-01 | [Rule] | file.py, line X | [impact] | [symptom] |
| I-[feature]-02 | [Rule] | file.py, line Y | [impact] | [symptom] |

---

## 3 · Module map

Which files own what?

| Path | Owns | Depends on |
|---|---|---|
| \`alppy/[module].py\` | [what it does] | [modules it needs] |
| \`alppy/[module]/\` | [what it does] | [modules it needs] |

---

## 4 · How to extend this feature

When adding to this subsystem:

1. **Read §2 invariants** — these are load-bearing rules
2. **List which invariants your change touches**
3. **Add a test** for each invariant affected
4. **Update this document** if you add new rules

### LLM Checklist

- [ ] Read §2 (Invariants) — these are not suggestions
- [ ] Which invariants does your change affect?
- [ ] Have you added a test for each affected invariant?
- [ ] Code comments cite invariants (e.g., # I-feature-01)
- [ ] Reviewed the decisions log (why each rule exists)

---

## 5 · Privacy & Safety

| Data | Scrubbing point | Why |
|---|---|---|
| [Student name] | [subsystem] | PII — never in LLM prompts |
| [Student ID] | [subsystem] | PII — never in image crops |

---

## 6 · Testing Strategy

Every invariant gets at least one test:

\`\`\`python
# tests/[feature]/test_invariants.py

def test_I_[feature]_01_[description]():
    \"\"\"I-[feature]-01: [Rule in plain English].\"\"\"
    # Arrange
    # Act
    # Assert
    pass
\`\`\`

Run all invariant tests:
\`\`\`bash
pytest tests/ -k test_I_ -v
\`\`\`

---

## Companion Documents

- \`architecture.md\` — Flow diagrams, component interaction
- \`decisions.md\` — D1, D2, D3… every major choice

---

**When was this last updated?** [DATE]
```

---

## Template: architecture.md for a Feature

Save as `docs/features/[feature-name]/architecture.md`:

```markdown
# [Feature Name] Architecture

## Component Diagram

\`\`\`
[Your flow diagram here]
\`\`\`

## Data Flow

### Input

\`\`\`python
class [InputClass]:
    field1: Type  # Why this field
    field2: Type  # Why this field
\`\`\`

### Output

\`\`\`python
class [OutputClass]:
    field1: Type  # What this represents
    field2: Type  # What this represents
\`\`\`

## Component Interaction

### Component A

[Description of what it does, which invariants it enforces]

### Component B

[Description of what it does, which invariants it enforces]

## Edge Cases

- **Case 1:** What happens when [condition]? → [Behavior enforced by I-feature-XX]
- **Case 2:** What happens when [condition]? → [Behavior enforced by I-feature-YY]

---

**Companion:** See README.md §2 (Invariants) for load-bearing rules.
```

---

## Template: decisions.md for a Feature

Save as `docs/features/[feature-name]/decisions.md`:

```markdown
# [Feature Name] Decisions Log

## D1: [Decision Title]

**Date:** YYYY-MM-DD  
**Owner:** [name]  
**Affected invariant:** I-feature-01

**Background:**
[Why this decision was needed. What problem did it solve?]

**Considered alternatives:**
- A) [Option] (rejected because: [reason])
- B) [Option] (rejected because: [reason])
- C) **[Chosen option]** (why: [reason])

**Tradeoff:**
- ✅ [Benefit]
- ✅ [Benefit]
- ❌ [Cost]

**How this reinforces I-feature-01:**
"[Quote the invariant]"

---

## D2: [Decision Title]

[Same format as D1]

---

## When Policy Changes

If you change a threshold, config, or business rule:

**Example:** D4 — "Why difficulty ≤ 1 level per cycle?"

\`\`\`json
{
  "change": "Increase from ±1 to ±2 difficulty levels",
  "reason": "Students are bored with slow progression",
  "date": "2026-09-15",
  "decision": "Rejected — would violate I-adaptation-02",
  "rationale": "A 2-level jump causes frustration & dropouts. Keep at ±1."
}
\`\`\`

---

**Keep this log updated.** Every major change gets a D-number.
```

---

## LLM Extension Checklist

When asking an LLM to modify a feature, provide this prompt:

```
You are extending the [FEATURE] module for the edtech platform.

BEFORE YOU CODE:
1. Read docs/features/[feature]/README.md (§2 Invariants are load-bearing)
2. Read docs/features/[feature]/decisions.md (understand the tradeoffs)
3. List which invariants your change touches
4. Explain why your change does NOT violate any of them

WHEN YOU CODE:
- Cite invariants in comments: # I-feature-01
- Write a test for each invariant you touch
- If you add a new rule, update README.md §2 first

BEFORE YOU SUBMIT:
- Run: pytest tests/ -k test_I_ -v
- Update decisions.md if you made a new choice
- Explain in the PR: "This change respects I-feature-XX"

EXAMPLE (what we're looking for):
"This adds retry logic for failed renders.

Invariants touched:
- I-sheets-01: Retry only for approved sheets (no change)
- I-sheets-05: Deterministic retry seed (new: add test_deterministic_retry)

New test: test_I_sheets_05_retry_deterministic()
```

---

## Test Coverage by Invariant

Every subsystem must have:

```
tests/[feature]/test_invariants.py
├─ test_I_[feature]_01_*
├─ test_I_[feature]_02_*
├─ test_I_[feature]_03_*
└─ test_I_[feature]_04_*
```

Run all:
```bash
pytest tests/ -k test_I_ -v --tb=short
```

---

## Audit Trail (Compliance)

Every critical path records why:

```python
# In the render path
def render_sheet_pdf(sheet: Sheet) -> bytes:
    # I-sheets-01: Approval gate
    if sheet.approved_at is None:
        audit_log.record(
            event="render_rejected",
            sheet_id=sheet.id,
            reason="I-sheets-01: Unapproved content",
            timestamp=now(),
        )
        raise PermissionError("I-sheets-01 violated")
    
    # I-sheets-05: Deterministic
    audit_log.record(
        event="render_start",
        sheet_id=sheet.id,
        layout_version=LAYOUT_VERSION,
        timestamp=now(),
    )
    
    pdf = _render_pdf(sheet)
    return pdf
```

---

## Emergency Procedures

Document what to do if a bug is found:

```markdown
## Emergency: Bug in [Feature]

### Detection
- [How you'd notice it]

### Response
1. [First step]
2. [Second step]
3. [Third step]

### Code
\`\`\`python
DISABLED_[FEATURE]_VERSIONS = [2]  # v2 had bug #456

def my_function():
    if version in DISABLED_[FEATURE]_VERSIONS:
        raise RuntimeError(f"Version {version} is disabled due to bug.")
\`\`\`
```

---

## Maintenance Checklist (Every Sprint)

- [ ] Update status line (draft → describes `main` as of DATE)
- [ ] Any invariants changed? Update §2 and add to decisions.md
- [ ] Any new modules? Add to §3 (module map)
- [ ] Any bugs found? Document in decisions.md with D-number
- [ ] Test coverage complete? Run `pytest tests/ -k test_I_`

---

## Quick Reference: Invariant Symbols

Use these in code to make invariants findable:

```python
# Invariant I-feature-01: [Rule]
if not condition:
    raise PermissionError("I-feature-01")

# Invariant I-feature-02: [Rule]
result = compute_safely()  # I-feature-02

# Invariant I-feature-03: [Rule]
assert valid_state  # I-feature-03
```

Search the codebase for `# I-` to find all enforcements:

```bash
grep -r "# I-" alppy/ tests/
```

---

## Next Steps

1. **Create feature directories:**
   ```bash
   mkdir -p docs/features/{sheets,scanning,grading,correction,adaptation,personalization}
   ```

2. **For each feature, create three files:**
   - `docs/features/[feature]/README.md` — Use the template above
   - `docs/features/[feature]/architecture.md` — Flow diagrams
   - `docs/features/[feature]/decisions.md` — D1, D2, etc.

3. **Update your PR template:**
   ```
   ## Invariants Affected
   - [ ] List which I-* invariants this touches
   
   ## Test Coverage
   - [ ] New test for each invariant touched
   ```

4. **Run before every merge:**
   ```bash
   pytest tests/ -k test_I_ -v
   ```

---

**End of Framework**

See `docs/features/[feature-name]/README.md` for specific feature documentation.
