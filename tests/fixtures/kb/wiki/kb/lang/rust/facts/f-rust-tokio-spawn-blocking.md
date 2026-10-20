---
id: f-rust-tokio-spawn-blocking
type: fact
domain: lang/rust
title: spawn_blocking moves blocking work to a dedicated thread
summary: Blocking calls or heavy compute inside an async task stop the worker 
  from driving other tasks; spawn_blocking hands the closure to the blocking 
  pool and returns a JoinHandle.
claim: tokio::task::spawn_blocking runs a closure on a thread dedicated to 
  blocking operations so the scheduler is not stalled.
kind: mechanism
confidence: sourced
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- spawn_blocking
- блокирующий код в tokio
- пул блокирующих потоков
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

tokio::task::spawn_blocking runs a closure on a thread dedicated to blocking operations so the scheduler is not stalled. [@src-tokio-docs гл. 2 "This function runs the provided closure on a thread dedicated to blocking operations"]

## Why

A worker thread blocked in a syscall cannot poll the other tasks in its queue.
