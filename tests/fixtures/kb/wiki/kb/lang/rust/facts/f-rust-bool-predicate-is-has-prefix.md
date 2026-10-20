---
id: f-rust-bool-predicate-is-has-prefix
type: fact
domain: lang/rust
title: 'Boolean accessors read as predicates: is_ and has_'
summary: Rust convention names boolean predicates is_empty, is_some, 
  has_remaining, and plain getters by the field name (len, capacity) without 
  get_; get_ is kept for the few indexed accessors.
claim: Methods and fields that answer a yes/no question are named with an is_ or
  has_ prefix, while plain getters have no get_ prefix.
kind: convention
confidence: sourced
scopes:
- domain:lang/rust
- layer:app
aliases:
- is_ и has_ для bool
- геттеры без get_
- именование предикатов
sources:
- src-rust-api-guidelines
relations:
  about:
  - top-rust-naming-conventions
  related:
  - f-rust-fn-naming-snake-case
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Methods and fields that answer a yes/no question are named with an is_ or has_ prefix, while plain getters have no get_ prefix. [@src-rust-api-guidelines гл. 1 "With a few exceptions, the get_ prefix is not used for getters in Rust code"]

## Why

`if vec.is_empty()` reads as a sentence; `get_` adds nothing when there is one obvious thing to get.
