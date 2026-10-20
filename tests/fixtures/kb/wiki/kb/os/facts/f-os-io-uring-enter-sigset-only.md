---
id: f-os-io-uring-enter-sigset-only
type: fact
domain: os
title: io_uring_enter has no wait timeout (before 5.11)
summary: Before IORING_FEAT_EXT_ARG (Linux 5.11) io_uring_enter(2) could not 
  take a timeout; waiting with a deadline meant submitting a timeout SQE 
  alongside the wait.
claim: The last argument of io_uring_enter is only a sigset_t; a bounded wait 
  needs an IORING_OP_TIMEOUT request.
kind: api
confidence: inferred
valid_for: linux>=5.1, linux<5.11
scopes:
- layer:kernel
- tech:io-uring
aliases:
- io_uring_enter без таймаута
- только sigset_t
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - tech-io-uring
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

The last argument of io_uring_enter is only a sigset_t; a bounded wait needs an IORING_OP_TIMEOUT request. [@src-man-io-uring-enter-2]

## Caveats

liburing hides the difference: io_uring_wait_cqe_timeout(3) falls back to a timeout SQE here.
