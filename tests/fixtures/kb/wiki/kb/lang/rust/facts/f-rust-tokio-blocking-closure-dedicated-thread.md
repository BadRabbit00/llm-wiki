---
id: f-rust-tokio-blocking-closure-dedicated-thread
type: fact
domain: lang/rust
title: Blocking closures go to a dedicated thread
summary: tokio::task::spawn_blocking hands the closure to the blocking thread 
  pool, keeping the scheduler's worker threads free to poll other tasks.
claim: spawn_blocking executes a blocking closure on a thread reserved for 
  blocking work so async workers keep running.
kind: mechanism
confidence: inferred
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- отдельный поток для блокировок
- spawn_blocking
sources:
- src-tokio-docs
relations:
  about:
  - tech-tokio
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

spawn_blocking executes a blocking closure on a thread reserved for blocking work so async workers keep running. [@src-tokio-docs]

## Caveats

The closure cannot be cancelled once it has started running.
