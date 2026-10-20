---
id: f-rust-fn-naming-snake-case
type: fact
domain: lang/rust
title: Functions, methods and variables are snake_case
summary: Rust names value-level items (functions, methods, variables, modules) 
  in snake_case; rustc's non_snake_case lint warns on other casing.
claim: Functions, methods, local variables and modules are named in snake_case.
kind: convention
confidence: sourced
scopes:
- domain:lang/rust
- layer:app
aliases:
- именование функций в Rust
- snake_case
- как называть функции
sources:
- src-rust-api-guidelines
relations:
  about:
  - top-rust-naming-conventions
  applies_with:
  - id: f-rust-doc-comment-triple-slash
    w: 0.8
    note: when writing a public fn, document it as well
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Functions, methods, local variables and modules are named in snake_case. [@src-rust-api-guidelines гл. 1 "Basic Rust naming conventions are described in RFC 430"]

## Why

One casing per item kind lets a reader tell a function from a type at a glance; the compiler lint enforces it.

## Example

```rust
fn parse_header(buf: &[u8]) -> Header { todo!() }
```
