---
id: f-rust-tokio-max-blocking-threads-512
type: fact
domain: lang/rust
title: The blocking pool allows 512 threads by default
summary: Builder::max_blocking_threads defaults to 512; once reached, 
  spawn_blocking tasks wait in a queue, which matters when the pool is used for 
  CPU-bound work.
claim: tokio's blocking thread pool is capped at 512 threads by default; further
  spawn_blocking calls queue.
kind: number
confidence: sourced
valid_for: tokio>=1.0
value: '512'
unit: threads
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- max_blocking_threads
- лимит блокирующих потоков
sources:
- src-tokio-docs
relations:
  about:
  - top-rust-tokio-runtime
  - tech-tokio
  refines:
  - f-rust-tokio-spawn-blocking
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

tokio's blocking thread pool is capped at 512 threads by default; further spawn_blocking calls queue. [@src-tokio-docs гл. 3 "The default value is 512"]

## Why

The limit is large because the pool mostly runs I/O that cannot be made asynchronous.
