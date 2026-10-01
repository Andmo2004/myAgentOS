---
name: git
description: Git repository operations, atomic commits, branch workflows, and clean history
version: 1.0.0
tags:
  - git
  - version-control
  - vcs
  - branches
  - commits
source: builtin
triggers:
  - git
  - commit
  - branch
  - merge
  - rebase
  - diff
  - worktree
  - repo
requires: []
related: []
risk_floor: LOW
requires_network: false
---

# Git Version Control Skill

## Purpose

Practices for maintaining clean git histories, branch isolation, atomic commits,
and safe worktree management.

## Guidelines

1. **Atomic Commits**:
   - Each commit should represent a single logical change.
   - Commit messages should be imperative and clearly explain the intent and rationale.

2. **Branch Workflows**:
   - Perform experimental or complex work in isolated branches or git worktrees.
   - Ensure working tree is verified and clean before merges.

3. **Protection & Hygiene**:
   - Never commit secrets, API keys, credentials, or transient `.env` files.
   - Use `.gitignore` to prevent committing build artifacts, cache files, and virtual environments.
