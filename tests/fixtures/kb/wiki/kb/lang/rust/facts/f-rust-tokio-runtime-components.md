---
id: f-rust-tokio-runtime-components
type: fact
domain: lang/rust
title: A tokio runtime bundles driver, scheduler, timer and blocking pool
summary: The tokio::runtime::Runtime is the unit that owns the I/O driver (epoll
  via mio), the task scheduler, timers and the pool for blocking work; async 
  tasks need all four to run.
claim: A tokio runtime provides an I/O driver, a task scheduler, a timer and a 
  blocking thread pool.
kind: definition
confidence: sourced
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- рантайм tokio
- компоненты tokio
- tokio::runtime
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

A tokio runtime provides an I/O driver, a task scheduler, a timer and a blocking thread pool. [@src-tokio-docs гл. 3 "The runtime provides an I/O driver, task scheduler, timer, and blocking pool, necessary for running asynchronous tasks"]

## Why

Separating the four parts lets the Builder tune each (threads, timers, I/O) independently.
