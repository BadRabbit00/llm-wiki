---
id: q-rust-tokio-uring-production-ready
type: question
domain: lang/rust
title: Is tokio-uring ready for a production file-serving path?
summary: 'Open: tokio-uring offers completion-based file I/O instead of tokio::fs
  blocking threads, but its single-thread runtime and owned-buffer API change the
  service structure; no team experience yet.'
priority: 3
scopes:
- domain:lang/rust
- layer:runtime
- tech:tokio
aliases:
- готов ли tokio-uring
- tokio-uring в проде
relations:
  about:
  - top-rust-tokio-runtime
  answered_by: []
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Context

tokio::fs is blocking I/O on the blocking pool ([[f-rust-tokio-fs-uses-blocking-pool]]); tokio-uring is a separate runtime ([[f-rust-tokio-uring-separate-runtime]]).

## What would answer it

A prototype of the static-file path with tokio-uring on Linux 6.x, compared with tokio::fs by throughput per core and tail latency.
