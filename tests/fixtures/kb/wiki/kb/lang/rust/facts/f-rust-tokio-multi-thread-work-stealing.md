---
id: f-rust-tokio-multi-thread-work-stealing
type: fact
domain: lang/rust
title: The multi-thread scheduler steals work between workers
summary: The default multi_thread runtime flavor keeps a run queue per worker 
  thread and lets idle workers steal tasks from busy ones, balancing load 
  without a central queue.
claim: tokio's multi-thread scheduler runs futures on a thread pool with a 
  work-stealing strategy.
kind: mechanism
confidence: sourced
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- планировщик tokio
- work stealing
- multi_thread
sources:
- src-tokio-docs
relations:
  about:
  - top-rust-tokio-runtime
  - tech-tokio
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

tokio's multi-thread scheduler runs futures on a thread pool with a work-stealing strategy. [@src-tokio-docs гл. 3 "The multi-thread scheduler executes futures on a thread pool, using a work-stealing strategy"]

## Why

Work stealing keeps locality for the common case and still spreads bursts across cores.
