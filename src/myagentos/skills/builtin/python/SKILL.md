---
name: python
description: Python software development conventions, type hints, and best practices
version: 1.0.0
tags:
  - python
  - backend
  - typing
  - fastapi
source: builtin
triggers:
  - python
  - py
  - fastapi
  - pytest
  - pip
  - pydantic
requires: []
related:
  - testing
  - debugging
risk_floor: LOW
requires_network: false
---

# Python Development Skill

## Purpose

Provides procedural standards and patterns for Python 3.12+ development, architecture,
and robust type system usage across myAgentOS.

## Core Conventions

1. **Modern Typing**:
   - Use standard collections for typing (`list[str]`, `dict[str, Any]`, `tuple[int, ...]`).
   - Use union syntax `X | None` instead of `Optional[X]`.
   - Use `Protocol` from `typing` for structural subtyping and decoupled interfaces.

2. **Immutable Data Modeling**:
   - Prefer frozen Pydantic models (`ConfigDict(frozen=True)`) or `@dataclass(frozen=True)`.
   - Never mutate shared collections in place when returning state from services.

3. **Error Handling**:
   - Derive all custom domain exceptions from a base package error (e.g. `MyAgentOSError`).
   - Chain exceptions with `from err` to preserve causal tracebacks.
   - Do not catch bare `Exception` without context or re-raising.

4. **Code Quality**:
   - Write clean, modular, self-contained functions with single responsibilities.
   - Accompany new functionality with deterministic unit tests.
