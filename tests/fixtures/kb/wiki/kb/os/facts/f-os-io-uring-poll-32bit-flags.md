---
id: f-os-io-uring-poll-32bit-flags
type: fact
domain: os
title: IORING_OP_POLL_ADD accepts full 32-bit epoll flags
summary: IORING_FEAT_POLL_32BITS (Linux 5.9) extends the poll mask of 
  IORING_OP_POLL_ADD from 16 to 32 bits so flags like EPOLLEXCLUSIVE can be used
  for shared wakeups.
claim: Since Linux 5.9 IORING_OP_POLL_ADD accepts the full 32-bit range of epoll
  flags, including EPOLLEXCLUSIVE.
kind: api
confidence: sourced
valid_for: linux>=5.9
scopes:
- layer:kernel
- tech:io-uring
aliases:
- 32-битные флаги poll
- IORING_FEAT_POLL_32BITS
- EPOLLEXCLUSIVE
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-multishot-timeouts-cancel
  replaces:
  - f-os-io-uring-poll-16bit-flags
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Since Linux 5.9 IORING_OP_POLL_ADD accepts the full 32-bit range of epoll flags, including EPOLLEXCLUSIVE. [@src-man-io-uring-setup-2 гл. 2 "the IORING_OP_POLL_ADD command accepts the full 32-bit range of epoll based flags. Most notably EPOLLEXCLUSIVE which allows shared poll wakeups"]

## Why

Accept-sharding servers rely on EPOLLEXCLUSIVE to avoid thundering herds.
