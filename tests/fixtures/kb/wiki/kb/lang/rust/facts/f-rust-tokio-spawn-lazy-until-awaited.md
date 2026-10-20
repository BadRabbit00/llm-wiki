---
id: f-rust-tokio-spawn-lazy-until-awaited
type: fact
domain: lang/rust
title: A spawned task waits for its JoinHandle to be awaited
summary: The belief that tokio::spawn is lazy like a plain future and the task 
  only makes progress while someone awaits the handle.
claim: A task passed to tokio::spawn does not start running until its JoinHandle
  is awaited.
kind: mechanism
confidence: contested
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- ленивый spawn
- задача ждёт await на JoinHandle
sources:
- src-tokio-docs
relations:
  about:
  - tech-tokio
  contradicts:
  - f-rust-tokio-spawn-runs-immediately
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

A task passed to tokio::spawn does not start running until its JoinHandle is awaited. [@src-tokio-docs]

## Caveats

Contradicts [[f-rust-tokio-spawn-runs-immediately]].
