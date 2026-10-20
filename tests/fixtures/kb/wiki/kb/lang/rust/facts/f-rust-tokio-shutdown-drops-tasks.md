---
id: f-rust-tokio-shutdown-drops-tasks
type: fact
domain: lang/rust
title: Runtime shutdown drops outstanding tasks
summary: 'There is no guarantee that a spawned task runs to completion: dropping the
  Runtime (or returning from #[tokio::main]) drops every pending task at its next
  yield point.'
claim: When a tokio runtime shuts down, all outstanding tasks are dropped 
  regardless of their state.
kind: pitfall
confidence: sourced
valid_for: tokio>=1.0
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- завершение рантайма
- незавершённые задачи
- graceful shutdown
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

When a tokio runtime shuts down, all outstanding tasks are dropped regardless of their state. [@src-tokio-docs гл. 2 "When a runtime is shutdown, all outstanding tasks are dropped, regardless of the lifecycle of that task"]

## Why

Cleanup that must happen (flush, close) needs an explicit await before shutdown.
