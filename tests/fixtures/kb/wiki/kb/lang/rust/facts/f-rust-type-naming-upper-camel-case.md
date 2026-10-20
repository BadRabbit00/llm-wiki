---
id: f-rust-type-naming-upper-camel-case
type: fact
domain: lang/rust
title: Types, traits and enum variants are UpperCamelCase
summary: Rust names type-level items (structs, enums and their variants, traits,
  type aliases) in UpperCamelCase; rustc's non_camel_case_types lint warns 
  otherwise.
claim: Types, traits, enum variants and type parameters are named in 
  UpperCamelCase.
kind: convention
confidence: sourced
scopes:
- domain:lang/rust
- layer:app
aliases:
- именование типов в Rust
- UpperCamelCase
- CamelCase для трейтов
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

Types, traits, enum variants and type parameters are named in UpperCamelCase. [@src-rust-api-guidelines гл. 1 "Casing conforms to RFC 430"]

## Why

Acronyms are treated as one word: `HttpRequest`, not `HTTPRequest`.
