---
id: f-rust-tokio-join-handle-detach
type: fact
domain: lang/rust
title: Dropping a JoinHandle detaches, it does not cancel
summary: A JoinHandle is not an owning handle; dropping it leaves the task 
  running on the runtime with no way to await its result, use JoinHandle::abort 
  to cancel.
claim: 'Dropping a tokio JoinHandle detaches the task: it keeps running and can no
  longer be joined.'
kind: pitfall
confidence: sourced
valid_for: tokio>=1.0
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- drop JoinHandle
- отсоединение задачи
- abort
sources:
- src-tokio-docs
relations:
  about:
  - top-rust-tokio-runtime
  - tech-tokio
  refines:
  - f-rust-tokio-spawn-runs-immediately
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Dropping a tokio JoinHandle detaches the task: it keeps running and can no longer be joined. [@src-tokio-docs гл. 2 "A JoinHandle detaches the associated task when it is dropped, which means that there is no longer any handle to the task, and no way to join on it"]

## Why

Matches thread semantics: a detached task is still alive, unlike a dropped future.
