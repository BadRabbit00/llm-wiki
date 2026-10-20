---
id: src-rust-book
type: source
title: The Rust Programming Language (the Rust Book)
summary: The official Rust Book; chapter 14 (Cargo and crates.io) describes 
  documentation comments /// and //! and rustdoc sections.
kind: book
url: https://doc.rust-lang.org/book/
raw_path: raw/docs/rust-book.txt
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

The official book of the Rust language. Citations use `гл.` = chapter number of the book; chapter 14 covers publishing crates, documentation comments and rustdoc.

## Ключевые факты

- [[f-rust-doc-comment-triple-slash]]: A public item is documented with a /// comment placed before it; rustdoc renders its Markdown.
- [[f-rust-inner-doc-comment-bang]]: A //! comment documents the item that contains it, typically the crate or module, rather than the item after it.

## Что изменилось в вики

Hand-written stage-1 corpus: [[top-rust-naming-conventions]]. No raw text is stored (raw_sha256 is the SHA-256 of empty input); quotes were checked against the published text by the author.
