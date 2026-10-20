---
id: f-rust-tokio-spawned-task-runs-unawaited
type: fact
domain: lang/rust
title: A spawned task runs even if its handle is ignored
summary: Once tokio::spawn is called the task is scheduled on the runtime 
  immediately, independent of whether the returned JoinHandle is awaited or 
  dropped.
claim: tokio::spawn begins executing the task right away; awaiting the 
  JoinHandle is not needed for it to make progress.
kind: mechanism
confidence: inferred
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- задача выполняется без await
- spawn запускает сразу
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

tokio::spawn begins executing the task right away; awaiting the JoinHandle is not needed for it to make progress. [@src-tokio-docs]

## Caveats

The spawned future must be Send and 'static on the multi-thread runtime.
