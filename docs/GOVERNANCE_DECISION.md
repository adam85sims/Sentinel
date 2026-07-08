# Governance Model Decision

> Which model/approach should Sentinel use for its governance audit?
> This document records the options, test results, and final decision.

## Context

Sentinel's governance harness verifies agent claims against independent
evidence. It needs an auditor model to compare claims vs evidence and
produce a structured report with findings.

The original build used `ibm/granite-4.1-3b` (fine-tuned as
`governance-granite`), but it over-triggered — hallucinating "actual: 0"
for test counts despite evidence showing otherwise.

## Options

### Option A: Base granite-4.1-3b + Deterministic Comparator

**How it works:**
- LLM (granite-4.1-3b) reads claims + evidence, produces JSON findings
- Deterministic comparator (`extract.py`) catches quantitative mismatches
  regardless of LLM output
- Safety net: if LLM disagrees with comparator, comparator wins

**Pros:**
- Already implemented and tested
- Deterministic comparator catches the hard errors (test count mismatches,
  missing files, future-dated diaries)
- LLM adds nuance for qualitative findings (wording diffs, logical gaps)

**Cons:**
- Requires LM Studio or vLLM running locally
- Fine-tuned governance model was unreliable (reverted to base)
- Base model still produces false positives on edge cases

**Requirements:**
- LM Studio with granite-4.1-3b loaded, OR
- vLLM serving granite-4.1-3b

### Option B: Different Small Model (qwen3.5, phi-3, gemma-2)

**How it works:**
- Same architecture as Option A, different LLM
- qwen3.5:9b is already available via Ollama on this machine

**Pros:**
- qwen3.5:9b already installed and running
- No fine-tuning needed — just needs a good prompt
- Potentially better reasoning than granite-4.1-3b

**Cons:**
- Untested — may have same over-triggering issues
- Different model = different failure modes to characterize
- Still requires a running inference server

**Requirements:**
- Ollama with qwen3.5:9b (already available)

### Option C: Pure Deterministic (No LLM)

**How it works:**
- `extract.py` comparator is the ONLY auditor
- No LLM call — pure regex + quantitative comparison
- Catches: test count mismatches, tool count mismatches, missing files,
  future dates, count discrepancies

**Pros:**
- Zero infrastructure — works anywhere
- Deterministic — same input always produces same output
- Fast — no inference time
- No hallucination risk
- Perfect for CI/CD pipelines

**Cons:**
- Misses qualitative issues (wording diffs, logical inconsistencies)
- Can't catch "agent claimed X but evidence shows subtle Y"
- Less nuanced than LLM-assisted audit

**Requirements:**
- None — pure Python

## Test Results

### Running on current codebase (2026-07-08)

**Note:** No diary entries exist in the sentinel project, so the audit
requires creating one first. The audit was tested on the original
automation framework codebase where diary entries exist.

#### Option A (granite-4.1-3b via LM Studio)
- **Status:** Not tested — LM Studio not running
- **Previous results:** Base model produces false positives on edge cases,
  fine-tuned model over-triggers on wording diffs

#### Option B (qwen3.5:9b via Ollama)
- **Status:** Available — Ollama running with qwen3.5:9b
- **Not yet tested** with governance prompts

#### Option C (Deterministic only)
- **Status:** Tested — works correctly
- **Results:**
  - Correctly identifies test count mismatches (CRITICAL)
  - Correctly identifies missing files (WARNING)
  - Correctly identifies future-dated diary entries (CRITICAL)
  - Does NOT catch qualitative wording issues (expected)

## Decision

### Recommended: Option C (Pure Deterministic) + Option B as optional upgrade

**Rationale:**

1. **CI/CD needs deterministic auditing.** When sentinel is published and
   used by others, the governance audit should work without a local LLM.
   Option C is the only option that works everywhere.

2. **The deterministic comparator already catches the hard errors.** The
   5 bugs found during the original build were ALL caught by the
   comparator, not the LLM. The LLM's qualitative findings were
   interesting but not critical.

3. **qwen3.5 can be an optional upgrade.** For users who want richer
   qualitative analysis, they can configure the auditor to use Ollama
   with qwen3.5. But the default should be deterministic.

4. **No hallucination risk.** The fine-tuned governance model's main
   failure mode was hallucinating counts. Pure deterministic has zero
   hallucination risk.

### Implementation

1. Set `backend.type: "none"` as the default in auditor.yaml
2. Keep the LLM auditor code for optional use
3. Make `extract.py` the primary audit mechanism
4. Document how to enable LLM auditing for richer analysis

## Follow-up

- [ ] Test qwen3.5 with governance prompts (Option B)
- [ ] Update auditor.yaml default to `type: "none"`
- [ ] Make LLM auditor optional in the audit pipeline
- [ ] Document the deterministic comparator's capabilities and limitations
