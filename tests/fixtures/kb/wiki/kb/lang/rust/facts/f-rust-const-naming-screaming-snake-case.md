---
id: f-rust-const-naming-screaming-snake-case
type: fact
domain: lang/rust
title: Constants and statics are SCREAMING_SNAKE_CASE
summary: Rust names `const` and `static` items in SCREAMING_SNAKE_CASE; rustc's 
  non_upper_case_globals lint warns on lower-case globals.
claim: Constants and statics are named in SCREAMING_SNAKE_CASE.
kind: convention
confidence: inferred
scopes:
- domain:lang/rust
- layer:app
aliases:
- именование констант в Rust
- SCREAMING_SNAKE_CASE
- константы заглавными
sources:
- src-rust-api-guidelines
relations:
  about:
  - top-rust-naming-conventions
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Constants and statics are named in SCREAMING_SNAKE_CASE. [@src-rust-api-guidelines]

## Why

Globals stand out from locals, which matters because a `const` pattern in a match is easy to confuse with a binding.
