---
id: f-os-io-uring-identity-kernel-threads
type: fact
domain: os
title: Async work ran on identity-assuming kernel threads (before 5.12)
summary: Before Linux 5.12 blocking requests were offloaded to io-wq kernel 
  threads that borrowed the credentials and mm of the owning task instead of 
  being threads of the process.
claim: io_uring async helpers are kernel threads that temporarily assume the 
  identity of the ring's owning task.
kind: mechanism
confidence: sourced
valid_for: linux>=5.1, linux<5.12
scopes:
- layer:kernel
- tech:io-uring
aliases:
- старые воркеры io-wq
- kernel threads с identity
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - tech-io-uring
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

io_uring async helpers are kernel threads that temporarily assume the identity of the ring's owning task. [@src-man-io-uring-setup-2 гл. 2 "Previous kernels used kernel threads that assumed the identity of the original io_uring owning task"]

## Caveats

Those helpers appeared as kernel threads in process listings, not under the application's PID.
