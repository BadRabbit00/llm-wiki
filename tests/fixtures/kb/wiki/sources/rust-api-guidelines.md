---
id: src-rust-api-guidelines
type: source
title: Rust API Guidelines
summary: 'Rust API Guidelines: naming (C-CASE, C-CONV, C-GETTER, C-ITER), documentation
  (C-EXAMPLE, C-FAILURE) and other checklist items for public Rust APIs.'
kind: doc
url: https://rust-lang.github.io/api-guidelines/
raw_path: raw/docs/rust-api-guidelines.txt
raw_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
ingested_at: '2026-10-20'
covers:
- top-rust-naming-conventions
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Кратко

The Rust API Guidelines checklist maintained by the Rust library team. Citations use `гл.` as a chapter locator: гл. 1 = Naming, гл. 2 = Interoperability, гл. 3 = Macros, гл. 4 = Documentation.

## Ключевые факты

- [[f-rust-fn-naming-snake-case]]: Functions, methods, local variables and modules are named in snake_case.
- [[f-rust-type-naming-upper-camel-case]]: Types, traits, enum variants and type parameters are named in UpperCamelCase.
- [[f-rust-rustdoc-sections-examples-panics-errors]]: Function documentation includes an Examples section and, when applicable, Panics, Errors and Safety sections.
- [[f-rust-conversion-prefixes-as-to-into]]: Ad-hoc conversion methods are prefixed as_ (free, borrowed), to_ (expensive, borrowed) or into_ (owned, consumes self).
- [[f-rust-bool-predicate-is-has-prefix]]: Methods and fields that answer a yes/no question are named with an is_ or has_ prefix, while plain getters have no get_ prefix.

## Что изменилось в вики

Hand-written stage-1 corpus: [[top-rust-naming-conventions]]. No raw text is stored (raw_sha256 is the SHA-256 of empty input); quotes were checked against the published text by the author.
