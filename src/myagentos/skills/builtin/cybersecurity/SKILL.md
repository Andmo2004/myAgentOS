---
name: cybersecurity
description: Security review, threat modeling, vulnerability analysis and secure coding
version: 1.0.0
tags:
  - security
  - cybersecurity
  - audit
  - owasp
  - authentication
  - authorization
source: builtin
triggers:
  - vulnerability
  - security audit
  - authentication
  - authorization
  - oauth
  - jwt
  - owasp
requires:
  - python
related:
  - testing
risk_floor: LOW
requires_network: false
---

# Cybersecurity Skill

## Purpose

Use this skill for application security analysis, threat modeling, secure code design,
and auditing authentication/authorization boundaries.

## Workflow

1. **Identify Attack Surface**:
   - Trace external input ingress points (APIs, CLI arguments, query parameters, webhooks).
   - Identify trust boundaries between components and external services.

2. **Inspect Authentication & Authorization**:
   - Verify token verification, signature validation, secret expiration, and revocation.
   - Enforce least privilege for authorization scopes and role checks.
   - Never allow unauthenticated access to control or state mutation routes.

3. **Audit Data Handling & Secrets**:
   - Check that credentials, API keys, tokens, and private data are never logged or persisted in plain text.
   - Verify that all retrieved memory is treated as untrusted contextual data.

4. **Verify OWASP Top 10 Protections**:
   - Check for SQL injection (use parameterized queries or ORMs).
   - Check for command injection (avoid raw shell execution, sanitize subprocess inputs).
   - Check for cross-site scripting (XSS) and SSRF risks.

## Constraints

- Never bypass system or project security policies.
- A security audit can elevate risk level, but never reduce it.
- Activating this skill never grants network or arbitrary execution permissions.
