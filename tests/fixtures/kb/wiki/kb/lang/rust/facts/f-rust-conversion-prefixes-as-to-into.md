---
id: f-rust-conversion-prefixes-as-to-into
type: fact
domain: lang/rust
title: Conversions are named as_, to_ or into_
summary: 'Rust API Guidelines name conversions by cost and ownership: as_ is a cheap
  borrow-to-borrow view, to_ an expensive conversion that keeps self, into_ consumes
  self and returns an owned value.'
claim: Ad-hoc conversion methods are prefixed as_ (free, borrowed), to_ 
  (expensive, borrowed) or into_ (owned, consumes self).
kind: convention
confidence: sourced
scopes:
- domain:lang/rust
- layer:app
aliases:
- as_ to_ into_
- именование конвертирующих методов
- конверсии в Rust
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

Ad-hoc conversion methods are prefixed as_ (free, borrowed), to_ (expensive, borrowed) or into_ (owned, consumes self). [@src-rust-api-guidelines гл. 1 "Ad-hoc conversions follow as_, to_, into_ conventions"]

## Why

The prefix tells the caller whether the call allocates and whether the receiver survives.

## Example

```rust
str::as_bytes(&self) -> &[u8]
str::to_owned(&self) -> String
String::into_bytes(self) -> Vec<u8>
```
