---
id: f-rust-tokio-current-thread-scheduler
type: fact
domain: lang/rust
title: The current-thread scheduler runs everything on one thread
summary: 'The current-thread scheduler is a single-threaded executor: tasks are created
  and polled on the thread that owns the runtime, so spawned futures need not be Send.'
claim: tokio's current_thread runtime flavor executes all tasks on the single 
  thread that runs the runtime.
kind: mechanism
confidence: sourced
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- current_thread
- однопоточный рантайм tokio
- flavor = current_thread
sources:
- src-tokio-docs
relations:
  about:
  - top-rust-tokio-runtime
  - tech-tokio
  related:
  - f-rust-tokio-multi-thread-work-stealing
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

tokio's current_thread runtime flavor executes all tasks on the single thread that runs the runtime. [@src-tokio-docs гл. 3 "The current-thread scheduler provides a single-threaded future executor"]

## Why

One runtime per core with current_thread is the shared-nothing layout tokio-uring and thread-per-core servers use.
