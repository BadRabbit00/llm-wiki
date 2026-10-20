---
id: f-rust-tokio-worker-threads-default-cores
type: fact
domain: lang/rust
title: Default worker thread count equals the CPU cores
summary: tokio's multi_thread flavor sizes its worker pool to the number of CPU 
  cores visible to the process (cgroup limits included); Builder::worker_threads
  overrides it.
claim: By default the multi-thread runtime starts one worker thread per CPU core
  available to the process.
kind: number
confidence: sourced
valid_for: tokio>=1.0
value: 1 per core
unit: threads
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- число воркеров tokio
- worker_threads
sources:
- src-tokio-docs
relations:
  about:
  - top-rust-tokio-runtime
  - tech-tokio
  refines:
  - f-rust-tokio-multi-thread-work-stealing
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

By default the multi-thread runtime starts one worker thread per CPU core available to the process. [@src-tokio-docs гл. 3 "By default, it will start a worker thread for each CPU core available on the system"]

## Why

More workers than cores only adds context switches for CPU-bound async work.
