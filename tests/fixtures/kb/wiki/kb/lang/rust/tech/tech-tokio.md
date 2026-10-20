---
id: tech-tokio
type: tech
domain: lang/rust
title: tokio
summary: 'The de facto asynchronous runtime for Rust: multi-thread work-stealing scheduler,
  epoll-based I/O driver, timers, sync primitives and a blocking pool.'
category: runtime
adoption: adopted
verdict: Default runtime for Rust services; use spawn_blocking for blocking work
  and tokio-uring only when io_uring completion I/O is measured to matter.
current_version: 1.x
homepage: https://tokio.rs/
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- tokio
- рантайм Rust
- async Rust
relations:
  instance_of:
  - top-rust-tokio-runtime
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Summary

Runtime crate with `#[tokio::main]`, `tokio::spawn`, `select!`, `tokio::sync`, `tokio::fs` and `tokio::net`. Its I/O model is readiness-based (mio over epoll), which is why file I/O runs on blocking threads.

## Our position

Adopted for all Rust services; version pinned per project lock file.
