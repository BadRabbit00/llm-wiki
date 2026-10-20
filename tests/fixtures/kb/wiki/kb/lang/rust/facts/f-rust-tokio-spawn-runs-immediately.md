---
id: f-rust-tokio-spawn-runs-immediately
type: fact
domain: lang/rust
title: tokio::spawn starts the task without awaiting the handle
summary: tokio::spawn schedules the task at once and returns a JoinHandle; 
  unlike a bare future, the spawned task makes progress whether or not anyone 
  awaits the handle.
claim: A future passed to tokio::spawn starts running in the background 
  immediately, even if the JoinHandle is never awaited.
kind: mechanism
confidence: sourced
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- tokio::spawn
- запуск задачи
- JoinHandle
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

A future passed to tokio::spawn starts running in the background immediately, even if the JoinHandle is never awaited. [@src-tokio-docs гл. 2 "The provided future will start running in the background immediately when spawn is called, even if you don't await the returned JoinHandle"]

## Why

Spawned tasks are the unit of concurrency; the runtime, not the caller, drives them.

## Caveats

spawn must be called inside a runtime context, otherwise it panics.
