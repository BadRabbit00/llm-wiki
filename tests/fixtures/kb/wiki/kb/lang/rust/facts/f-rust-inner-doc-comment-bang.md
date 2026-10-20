---
id: f-rust-inner-doc-comment-bang
type: fact
domain: lang/rust
title: //! documents the enclosing item
summary: Inner doc comments (//!) attach to the enclosing crate or module and 
  are used at the top of lib.rs or a module file; outer /// comments attach to 
  the following item.
claim: A //! comment documents the item that contains it, typically the crate or
  module, rather than the item after it.
kind: convention
confidence: sourced
scopes:
- domain:lang/rust
- layer:app
aliases:
- //! комментарий
- документация crate
- внутренний doc-комментарий
sources:
- src-rust-book
relations:
  about:
  - top-rust-naming-conventions
  refines:
  - f-rust-doc-comment-triple-slash
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

A //! comment documents the item that contains it, typically the crate or module, rather than the item after it. [@src-rust-book гл. 14 "adds documentation to the item that contains the comments rather than to the items following the comments"]

## Why

A crate root has no preceding item to attach a /// comment to.
