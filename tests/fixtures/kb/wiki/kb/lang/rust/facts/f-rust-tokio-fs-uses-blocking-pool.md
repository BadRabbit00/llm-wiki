---
id: f-rust-tokio-fs-uses-blocking-pool
type: fact
domain: lang/rust
title: tokio::fs is blocking I/O on the blocking pool
summary: 'File I/O in tokio is not asynchronous at the kernel level: each tokio::fs
  call is executed with blocking syscalls on a blocking-pool thread, so it costs a
  thread hop per operation.'
claim: tokio::fs performs ordinary blocking file operations on the 
  spawn_blocking pool because most OSes lack async file APIs.
kind: pitfall
confidence: sourced
valid_for: tokio>=1.0
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- tokio::fs
- файловый ввод-вывод tokio
- блокирующие файлы
sources:
- src-tokio-docs
relations:
  about:
  - top-rust-tokio-runtime
  - tech-tokio
  applies_with:
  - id: f-rust-tokio-max-blocking-threads-512
    w: 0.7
    note: heavy file I/O competes for the same 512 threads
  refines:
  - f-rust-tokio-spawn-blocking
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

tokio::fs performs ordinary blocking file operations on the spawn_blocking pool because most OSes lack async file APIs. [@src-tokio-docs гл. 4 "Be aware that most operating systems do not provide asynchronous file system APIs. Because of that, Tokio will use ordinary blocking file operations behind the scenes"]

## Why

Linux has no portable readiness notification for regular files; io_uring is the exception.
