---
id: f-rust-tokio-select-drops-unfinished
type: fact
domain: lang/rust
title: select! drops the unfinished branches
summary: tokio::select! resolves with the first ready branch and cancels the 
  rest by dropping their futures, losing any partial progress they held.
claim: When one branch of tokio::select! completes, the futures of the other 
  branches are dropped and thus cancelled.
kind: mechanism
confidence: inferred
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- select! отбрасывает ветки
- отмена через drop
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

When one branch of tokio::select! completes, the futures of the other branches are dropped and thus cancelled. [@src-tokio-docs]

## Caveats

Pin a future outside the loop with tokio::pin! to keep it across iterations.
