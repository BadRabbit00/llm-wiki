---
id: f-os-io-uring-enter-ext-arg-timeout
type: fact
domain: os
title: io_uring_enter can take a wait timeout since 5.11
summary: IORING_FEAT_EXT_ARG (Linux 5.11) lets io_uring_enter(2) wait for 
  completions with a timeout passed in struct io_uring_getevents_arg, instead of
  arming an IORING_OP_TIMEOUT request.
claim: With IORING_ENTER_EXT_ARG io_uring_enter receives struct 
  io_uring_getevents_arg carrying both a sigset and a wait timeout.
kind: api
confidence: sourced
valid_for: linux>=5.11
scopes:
- layer:kernel
- tech:io-uring
aliases:
- таймаут ожидания io_uring_enter
- IORING_ENTER_EXT_ARG
- io_uring_wait_cqe_timeout
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-multishot-timeouts-cancel
  replaces:
  - f-os-io-uring-enter-sigset-only
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

With IORING_ENTER_EXT_ARG io_uring_enter receives struct io_uring_getevents_arg carrying both a sigset and a wait timeout. [@src-man-io-uring-setup-2 гл. 2 "allows the caller to pass in both a sigset_t and a timeout argument for waiting on events"]

## Why

liburing's io_uring_wait_cqe_timeout(3) uses it when available and falls back to a timeout SQE otherwise.
