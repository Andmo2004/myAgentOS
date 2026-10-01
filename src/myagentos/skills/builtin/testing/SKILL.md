---
name: testing
description: Testing strategy, test suites, pytest best practices, and verification
version: 1.0.0
tags:
  - testing
  - test
  - pytest
  - verification
  - coverage
source: builtin
triggers:
  - test
  - tests
  - pytest
  - unittest
  - coverage
  - verification
  - mock
requires: []
related:
  - debugging
risk_floor: LOW
requires_network: false
---

# Testing & Verification Skill

## Purpose

Guidance on writing comprehensive, isolated, and fast test suites using pytest,
fixtures, and deterministic mocks.

## Guidelines

1. **Isolation**:
   - Every test must be completely isolated and clean up temporary resources.
   - Use `tmp_path` fixture for filesystem tests.
   - Never rely on or pollute real developer environment variables or `.env` files.

2. **Deterministic Assertions**:
   - Do not rely on external networks or live LLM API calls in automated test suites.
   - Use `MockProviderAdapter` or capturing adapters for LLM gateway validation.
   - Verify both positive and adversarial/edge cases (empty inputs, invalid tokens, boundary values).

3. **Async Testing**:
   - Mark asynchronous tests with `@pytest.mark.asyncio`.
   - Properly await all async operations and pilot events in UI tests.
