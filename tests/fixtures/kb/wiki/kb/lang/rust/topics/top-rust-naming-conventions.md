---
id: top-rust-naming-conventions
type: topic
domain: lang/rust
title: Naming and documentation conventions in Rust
summary: How Rust items are named (snake_case, UpperCamelCase, 
  SCREAMING_SNAKE_CASE, as_/to_/into_, is_/has_) and documented (/// and //!, 
  Examples, Panics, Errors sections).
priority: 3
scopes:
- domain:lang/rust
- layer:app
aliases:
- именование в Rust
- соглашения Rust
- документирование кода Rust
relations:
  related:
  - top-rust-tokio-runtime
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Digest

Rust casing follows RFC 430: snake_case for functions, methods, variables and modules; UpperCamelCase for types, traits and enum variants; SCREAMING_SNAKE_CASE for constants and statics, each enforced by a rustc lint. Conversions are named by cost and ownership: as_ (cheap borrow), to_ (expensive, keeps self), into_ (consumes self); boolean accessors read as predicates with is_ or has_, and getters drop the get_ prefix. Public items are documented with /// Markdown comments rendered by rustdoc, crates and modules with //!, and function docs carry Examples plus Panics, Errors and Safety sections where they apply.

## Facts

1. [[f-rust-fn-naming-snake-case]]
2. [[f-rust-type-naming-upper-camel-case]]
3. [[f-rust-const-naming-screaming-snake-case]]
4. [[f-rust-conversion-prefixes-as-to-into]]
5. [[f-rust-bool-predicate-is-has-prefix]]
6. [[f-rust-doc-comment-triple-slash]]
7. [[f-rust-inner-doc-comment-bang]]
8. [[f-rust-rustdoc-sections-examples-panics-errors]]
