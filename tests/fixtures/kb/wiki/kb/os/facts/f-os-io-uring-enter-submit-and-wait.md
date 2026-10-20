---
id: f-os-io-uring-enter-submit-and-wait
type: fact
domain: os
title: io_uring_enter submits and waits in one call
summary: io_uring_enter(2) takes to_submit and min_complete so that a single 
  system call submits a batch and blocks for completions of this or previous 
  calls.
claim: One io_uring_enter(2) call can both submit new SQEs and wait for 
  completions of earlier ones.
kind: api
confidence: sourced
valid_for: linux>=5.1
scopes:
- layer:kernel
- tech:io-uring
aliases:
- io_uring_enter
- отправка и ожидание одним вызовом
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-submission
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

One io_uring_enter(2) call can both submit new SQEs and wait for completions of earlier ones. [@src-man-io-uring-enter-2 гл. 2 "A single call can both submit new I/O and wait for completions of I/O initiated by this call or previous calls to io_uring_enter()"]

## Why

Collapsing submit and wait halves the syscalls of a classic submit/poll loop.
