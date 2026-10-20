---
id: top-rust-tokio-runtime
type: topic
domain: lang/rust
title: 'tokio runtime: scheduling, spawning and blocking'
summary: 'How tokio runs async Rust: runtime components, work-stealing workers, spawn
  and JoinHandle semantics, select! cancellation, the blocking pool, blocking file
  I/O and the io_uring gap.'
priority: 5
scopes:
- domain:lang/rust
- layer:runtime
- tech:tokio
aliases:
- рантайм tokio
- планирование задач tokio
- tokio и io_uring
relations:
  related:
  - top-os-io-uring-ring-model
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Digest

A tokio Runtime owns an I/O driver, scheduler, timer and blocking pool. The multi_thread flavor runs one work-stealing worker per core. tokio::spawn starts a task immediately; dropping its JoinHandle detaches rather than cancels, and runtime shutdown drops every outstanding task. select! drops the losing branches, so non cancellation-safe futures lose state. Blocking work goes to spawn_blocking (512 threads by default), which is also how tokio::fs does file I/O. The I/O driver is readiness-based on epoll; io_uring needs the separate tokio-uring runtime.

## Facts

1. [[f-rust-tokio-runtime-components]]
2. [[f-rust-tokio-multi-thread-work-stealing]]
3. [[f-rust-tokio-worker-threads-default-cores]]
4. [[f-rust-tokio-current-thread-scheduler]]
5. [[f-rust-tokio-spawn-runs-immediately]]
6. [[f-rust-tokio-join-handle-detach]]
7. [[f-rust-tokio-shutdown-drops-tasks]]
8. [[f-rust-tokio-select-cancels-losers]]
9. [[f-rust-tokio-select-random-branch-order]]
10. [[f-rust-tokio-spawn-blocking]]
11. [[f-rust-tokio-max-blocking-threads-512]]
12. [[f-rust-tokio-fs-uses-blocking-pool]]
13. [[f-rust-tokio-io-driver-epoll-readiness]]
14. [[f-rust-tokio-uring-separate-runtime]]

## Open questions

- [[q-rust-tokio-uring-production-ready]]
