---
name: database
description: Database architecture, relational schemas, indexing, migrations, and queries
version: 1.0.0
tags:
  - database
  - sql
  - sqlite
  - postgresql
  - migrations
source: builtin
triggers:
  - database
  - base de datos
  - bases de datos
  - db
  - sql
  - sqlite
  - postgres
  - postgresql
  - schema
  - esquema
  - migration
  - migraciones
  - orm
requires: []
related:
  - python
risk_floor: LOW
requires_network: false
---

# Database Engineering Skill

## Purpose

Design, optimization, and migration workflows for relational and embedded databases
(SQLite, PostgreSQL).

## Rules & Principles

1. **Migration Governance**:
   - Migrations are durable and append-only. Never modify or delete previously executed migrations in production environments.
   - Every migration must be tested forwards and backwards (rollback plan).

2. **Query Performance**:
   - Index columns used frequently in `WHERE`, `JOIN`, and `ORDER BY` clauses.
   - Avoid N+1 query patterns; use eager loading or batch queries when retrieving relational records.
   - Use `EXPLAIN QUERY PLAN` on complex queries to check for table scans.

3. **Data Integrity & Security**:
   - Always use parameterized queries; never construct SQL statements using raw string interpolation.
   - Define foreign key constraints and transaction boundaries explicitly.
