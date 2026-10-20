---
id: f-rust-tokio-select-keeps-losers-polling
type: fact
domain: lang/rust
title: select! keeps polling the branches that lost
summary: The belief that select! only reports the first ready branch and leaves 
  the other futures running in the background.
claim: tokio::select! keeps polling the branches that did not complete so that 
  they finish later.
kind: mechanism
confidence: contested
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- select! не отменяет ветки
- проигравшие ветки продолжают
sources:
- src-tokio-docs
relations:
  about:
  - tech-tokio
  contradicts:
  - f-rust-tokio-select-cancels-losers
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

tokio::select! keeps polling the branches that did not complete so that they finish later. [@src-tokio-docs]

## Caveats

Contradicts [[f-rust-tokio-select-cancels-losers]].
