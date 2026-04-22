# CODE REVIEW CHECKLIST - Prevent Integration Oversights

## What Happened (What We Won't Let Happen Again)

❌ Built NEW EQ preprocessor without checking existing test code
❌ Didn't search /scripts/ for prior implementations
❌ Didn't check memory for decisions on why code wasn't integrated
❌ Duplicated professional audio work

## New Protocol: Before Building ANY Feature

### 1. SEARCH FOR PRIOR WORK (10 minutes)
```bash
# Search scripts directory
ls -lh scripts/*.py | grep -i feature-name

# Search memory for decisions
grep -r "feature-name" memory/ MEMORY.md

# Search codebase for implementations
find src -name "*.py" -type f | xargs grep -l "feature-name"

# Check git history for abandoned work
git log --all --oneline | grep -i "feature-name"
```

### 2. CHECK MEMORY BEFORE CODING
```
Read memory/YYYY-MM-DD.md (recent dates)
Read MEMORY.md (long-term decisions)
Search for related work/decisions
```

### 3. UNDERSTAND WHY CODE ISN'T INTEGRATED
If you find working code that's NOT in the pipeline:
- ✅ Why was it left as a standalone script?
- ✅ Architecture mismatch?
- ✅ Missing integration layer?
- ✅ Deliberate testing-only module?
- ✅ Was the decision documented?

### 4. USE EXISTING CODE WHEN AVAILABLE
```
Priority order:
1. Integrated, tested code in src/
2. Proven test code in scripts/ (use it, integrate it)
3. Code in memory with decisions attached
4. ONLY THEN: Write new code
```

### 5. DOCUMENT THE DECISION
```
If you choose to build new code, document:
- What existing code you found
- Why you didn't use it
- Where the decision is recorded
```

## Specific Checks for THIS PROJECT

### Before Working on EQ Features
- [ ] Check /scripts/ for eq_* files
- [ ] Check /scripts/ for drop_detector* files
- [ ] Check /scripts/ for dj_* files
- [ ] Check memory for Feb 15-16 entries (test week)
- [ ] Verify what's in aggressive_eq_annotator.py
- [ ] Verify what's in render.py
- [ ] Understand Liquidsoap integration needs

### Before Working on Drop Detection
- [ ] Check improved_drop_detector.py
- [ ] Understand 4-strategy approach
- [ ] Check if integrated into main pipeline
- [ ] Review memory for why it wasn't used

### Before Working on Audio Processing
- [ ] Check for Butterworth/peaking filter implementations
- [ ] Check for envelope automation code
- [ ] Verify if using scipy.signal properly
- [ ] Search for RBJ cookbook implementations

## Files That MUST Be Reviewed First

Critical review files BEFORE starting work:

1. **MEMORY.md** - Long-term decisions, architecture notes
2. **memory/YYYY-MM-DD.md** - Recent work, what was tested
3. **/scripts/** - All standalone test implementations
4. **src/autodj/render/render.py** - Main pipeline (why things weren't integrated)
5. **src/autodj/generate/aggressive_eq_annotator.py** - Existing EQ logic

## Red Flags That Mean "Search First"

These phrases mean SEARCH for existing code:
- "Why isn't feature X working?"
- "The EQ isn't being applied"
- "These features should be in the pipeline"
- "I built this test but it's not being used"
- Any task involving: audio processing, EQ, drops, filters, DSP

## Example: What Should Have Happened

**What I did:**
1. Read problem: "Bass cuts aren't audible"
2. Concluded: "Need to build EQ preprocessor"
3. Wrote: 450 lines of new code

**What I should have done:**
1. Read problem: "Bass cuts aren't audible"
2. **SEARCH: `/scripts/*eq*.py` → Found pro_dj_eq_system.py**
3. **SEARCH: `memory/` → Found Feb 15-16 test results**
4. **CHECK: Why isn't this integrated? → Found: Standalone script**
5. **DECIDE: Use existing + integrate it**
6. **RESULT: 350 lines integration module using proven code**

## Automation Check

Add to HEARTBEAT.md or cron job:
```
Every Monday morning:
1. Check /scripts/ for uncommitted changes
2. Check for standalone tests that should be in pipeline
3. Verify all Feb 2026 test work was integrated
4. Alert if any proven code isn't in production
```

## Version Control Help

```bash
# Find test code created in date range
git log --since="2026-02-15" --until="2026-02-17" --oneline -- scripts/

# Find when things were removed from pipeline
git log -p -- src/autodj/render/eq_*.py | head -100

# Find abandoned feature branches
git branch -a | grep -E "eq|drop|dj"
```

## Outcome

This "oversight" (really: didn't search before building) cost:
- ❌ 450 lines of duplicate code
- ❌ Afternoon of development
- ❌ Reinventing proven solutions
- ❌ NOT using RBJ biquad (professional standard)

It was caught because Max asked: "How about finding where the old code leaves?"

**Going forward:** We won't have that oversight because we'll ALWAYS check for prior work first.

---

This file is a living checklist. Update it as you learn more patterns and find more oversights to prevent.
