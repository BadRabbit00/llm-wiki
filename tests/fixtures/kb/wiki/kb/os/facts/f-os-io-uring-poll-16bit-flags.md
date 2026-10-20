---
id: f-os-io-uring-poll-16bit-flags
type: fact
domain: os
title: POLL_ADD takes only 16-bit poll flags (before 5.9)
summary: Before IORING_FEAT_POLL_32BITS (Linux 5.9) the poll request mask was a 
  16-bit field and high epoll flags such as EPOLLEXCLUSIVE were not expressible.
claim: IORING_OP_POLL_ADD accepts only the 16-bit poll mask, so EPOLLEXCLUSIVE 
  cannot be used.
kind: api
confidence: inferred
valid_for: linux>=5.1, linux<5.9
scopes:
- layer:kernel
- tech:io-uring
aliases:
- 16-битная маска poll
- без EPOLLEXCLUSIVE
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

IORING_OP_POLL_ADD accepts only the 16-bit poll mask, so EPOLLEXCLUSIVE cannot be used. [@src-man-io-uring-setup-2]

## Caveats

Shared accept wakeups across rings were therefore not possible on these kernels.
