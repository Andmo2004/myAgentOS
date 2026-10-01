---
name: debugging
description: Systematic debugging, root cause analysis, error reproduction and trace inspection
version: 1.0.0
tags:
  - debugging
  - troubleshooting
  - trace
  - errors
source: builtin
triggers:
  - debug
  - error
  - exception
  - trace
  - bug
  - failure
  - crash
requires: []
related:
  - testing
risk_floor: LOW
requires_network: false
---

# Debugging Skill

## Purpose

Systematic workflow for reproducing bugs, analyzing root causes, and implementing minimal,
targeted fixes without unintended side effects.

## Workflow

1. **Reproduction**:
   - Write a minimal failing test that reproduces the reported issue reliably.
   - Inspect the exact exception type, message, and callstack.

2. **Root Cause Analysis**:
   - Trace the causal chain backwards to identify where invalid assumptions or state mutations occurred.
   - Differentiate symptoms from the underlying fault.

3. **Targeted Remediation**:
   - Make the smallest possible change that addresses the root cause directly.
   - Ensure existing comments, docstrings, and invariants are preserved.
   - Run the full test suite to guarantee zero regressions.
