---
id: f-rust-tokio-join-handle-drop-aborts
type: fact
domain: lang/rust
title: Dropping a JoinHandle aborts the task
summary: The belief that the JoinHandle owns the task, so letting it go out of 
  scope aborts the task the way dropping a future does.
claim: Dropping a tokio JoinHandle cancels the spawned task immediately.
kind: pitfall
confidence: contested
valid_for: tokio>=1.0
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- drop JoinHandle отменяет задачу
- JoinHandle владеет задачей
sources:
- src-tokio-docs
relations:
  about:
  - tech-tokio
  contradicts:
  - f-rust-tokio-join-handle-detach
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Dropping a tokio JoinHandle cancels the spawned task immediately. [@src-tokio-docs]

## Caveats

Contradicts [[f-rust-tokio-join-handle-detach]].
