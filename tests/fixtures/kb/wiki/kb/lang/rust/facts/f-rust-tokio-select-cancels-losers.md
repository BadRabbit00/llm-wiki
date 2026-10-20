---
id: f-rust-tokio-select-cancels-losers
type: fact
domain: lang/rust
title: select! drops the branches that did not complete
summary: select! polls all branches concurrently; once one finishes, the other 
  futures are dropped, so any state they held mid-operation is lost unless the 
  future is cancellation safe.
claim: tokio::select! returns when the first branch completes and cancels the 
  remaining branches by dropping their futures.
kind: mechanism
confidence: sourced
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- tokio::select!
- отмена веток select
- cancellation safety
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

tokio::select! returns when the first branch completes and cancels the remaining branches by dropping their futures. [@src-tokio-docs гл. 5 "Waits on multiple concurrent branches, returning when the first branch completes, cancelling the remaining branches"]

## Why

Dropping is the only cancellation primitive in Rust async; select! relies on it.

## Caveats

read_exact and similar multi-step futures are not cancellation safe; restart them from scratch after a lost select.
