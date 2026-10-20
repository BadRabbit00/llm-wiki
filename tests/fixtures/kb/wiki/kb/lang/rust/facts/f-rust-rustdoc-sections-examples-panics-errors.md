---
id: f-rust-rustdoc-sections-examples-panics-errors
type: fact
domain: lang/rust
title: Function docs carry Examples, Panics, Errors and Safety sections
summary: 'Rust API docs use conventional H1 sections in the doc comment: `# Examples`
  with runnable code, `# Panics` for panic conditions, `# Errors` for the Err variants,
  `# Safety` for unsafe contracts.'
claim: Function documentation includes an Examples section and, when applicable,
  Panics, Errors and Safety sections.
kind: convention
confidence: sourced
scopes:
- domain:lang/rust
- layer:app
aliases:
- разделы rustdoc
- '# Examples # Panics # Errors'
- документация ошибок и паник
sources:
- src-rust-api-guidelines
relations:
  about:
  - top-rust-naming-conventions
  applies_with:
  - id: f-rust-doc-comment-triple-slash
    w: 0.8
    note: the sections live inside the /// comment of the item
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Function documentation includes an Examples section and, when applicable, Panics, Errors and Safety sections. [@src-rust-api-guidelines гл. 4 "Function docs include error, panic, and safety considerations"]

## Why

Examples are compiled as doctests, so they double as tests of the public API.
