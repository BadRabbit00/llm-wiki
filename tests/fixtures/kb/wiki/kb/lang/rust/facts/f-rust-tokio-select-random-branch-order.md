---
id: f-rust-tokio-select-random-branch-order
type: fact
domain: lang/rust
title: select! checks branches in random order by default
summary: To stay fair when several branches are always ready, select! randomises
  the polling order on every evaluation; writing `biased;` as the first line 
  polls branches in source order instead.
claim: tokio::select! randomly picks which branch to poll first; the biased; 
  modifier makes the order top-down.
kind: mechanism
confidence: sourced
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- порядок веток select!
- biased
- справедливость select!
sources:
- src-tokio-docs
relations:
  about:
  - top-rust-tokio-runtime
  - tech-tokio
  related:
  - f-rust-tokio-select-cancels-losers
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

tokio::select! randomly picks which branch to poll first; the biased; modifier makes the order top-down. [@src-tokio-docs гл. 5 "By default, select! randomly picks a branch to check first"]

## Why

A loop whose first branch is always ready would otherwise starve the others.
