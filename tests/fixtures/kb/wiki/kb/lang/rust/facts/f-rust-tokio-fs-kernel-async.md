---
id: f-rust-tokio-fs-kernel-async
type: fact
domain: lang/rust
title: tokio::fs is asynchronous at the kernel level
summary: The belief that tokio's file API is driven by the I/O driver like 
  sockets, with no thread hop per operation.
claim: tokio::fs performs file operations asynchronously in the kernel without 
  using blocking threads.
kind: pitfall
confidence: contested
valid_for: tokio>=1.0
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- tokio::fs асинхронен в ядре
- файлы без блокирующих потоков
sources:
- src-tokio-docs
relations:
  about:
  - tech-tokio
  contradicts:
  - f-rust-tokio-fs-uses-blocking-pool
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

tokio::fs performs file operations asynchronously in the kernel without using blocking threads. [@src-tokio-docs]

## Caveats

Contradicts [[f-rust-tokio-fs-uses-blocking-pool]].
