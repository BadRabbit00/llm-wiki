---
id: f-rust-doc-comment-triple-slash
type: fact
domain: lang/rust
title: Public items are documented with /// doc comments
summary: Rust documentation comments start with three slashes, support Markdown 
  and are turned into HTML by rustdoc (cargo doc); they document the item that 
  follows them.
claim: A public item is documented with a /// comment placed before it; rustdoc 
  renders its Markdown.
kind: convention
confidence: sourced
scopes:
- domain:lang/rust
- layer:app
aliases:
- doc-комментарии в Rust
- ///
- документирование функций
sources:
- src-rust-book
relations:
  about:
  - top-rust-naming-conventions
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

A public item is documented with a /// comment placed before it; rustdoc renders its Markdown. [@src-rust-book гл. 14 "Documentation comments use three slashes, ///, instead of two and support Markdown notation for formatting the text"]

## Why

Documentation lives next to the code and compiles into docs.rs pages and doctests.

## Example

```rust
/// Adds one to the given number.
pub fn add_one(x: i32) -> i32 { x + 1 }
```
