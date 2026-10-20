---
id: f-rust-tokio-io-driver-epoll-readiness
type: fact
domain: lang/rust
title: tokio's I/O driver is readiness-based on epoll
summary: tokio sockets register with mio (epoll on Linux) and perform the read 
  or write syscall themselves when readiness arrives; the runtime does not 
  submit I/O to io_uring.
claim: "tokio's I/O driver uses mio over epoll on Linux: readiness notification, not
  io_uring completion."
kind: comparison
confidence: inferred
scopes:
- domain:lang/rust
- layer:runtime
aliases:
- tokio и epoll
- readiness против completion
- mio
sources:
- src-tokio-docs
relations:
  about:
  - top-rust-tokio-runtime
  - tech-tokio
  related:
  - top-os-io-uring-ring-model
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

tokio's I/O driver uses mio over epoll on Linux: readiness notification, not io_uring completion. [@src-tokio-docs]

## Why

The readiness model keeps buffers owned by the task; a completion model needs the kernel to own them during I/O.

## Caveats

Hence tokio::fs falls back to blocking threads and tokio-uring exists as a separate runtime.
