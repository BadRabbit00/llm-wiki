---
id: f-rust-tokio-uring-separate-runtime
type: fact
domain: lang/rust
title: tokio-uring is a separate io_uring-backed runtime
summary: The tokio-uring crate exposes a current-thread runtime built on 
  io_uring with owned-buffer resource types (File, TcpStream); ordinary 
  tokio-based libraries still run inside it.
claim: tokio-uring provides its own runtime that drives io_uring resources while
  staying compatible with tokio libraries.
kind: comparison
confidence: inferred
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- tokio-uring
- io_uring в Rust
- рантайм tokio-uring
sources:
- src-tokio-uring-docs
relations:
  about:
  - top-rust-tokio-runtime
  - tech-tokio
  applies_with:
  - id: f-os-io-uring-shared-rings
    w: 0.6
    note: tokio-uring submits SQEs to these rings on behalf of Rust futures
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

tokio-uring provides its own runtime that drives io_uring resources while staying compatible with tokio libraries. [@src-tokio-uring-docs]

## Why

Completion-based I/O needs buffers handed to the kernel by value, which tokio's AsyncRead trait cannot express.

## Caveats

Its I/O APIs take and return buffers by value; it is a single-threaded runtime per core and not drop-in for multi_thread code.
