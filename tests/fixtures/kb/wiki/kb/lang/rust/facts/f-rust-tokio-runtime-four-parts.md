---
id: f-rust-tokio-runtime-four-parts
type: fact
domain: lang/rust
title: tokio's Runtime consists of four parts
summary: 'Running async tasks in tokio requires the four services bundled in Runtime:
  I/O driver, task scheduler, timer and blocking pool.'
claim: A tokio Runtime is made of an I/O driver, a scheduler, a timer and a pool
  for blocking tasks.
kind: definition
confidence: inferred
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- четыре части рантайма
- устройство Runtime
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

A tokio Runtime is made of an I/O driver, a scheduler, a timer and a pool for blocking tasks. [@src-tokio-docs]

## Caveats

Each part can be disabled or sized through tokio::runtime::Builder.
