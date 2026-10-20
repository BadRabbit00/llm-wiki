---
id: f-os-io-uring-enter-registered-ring
type: fact
domain: os
title: IORING_ENTER_REGISTERED_RING passes the registered ring index
summary: After IORING_REGISTER_RING_FDS, io_uring_enter(2) must be called with 
  IORING_ENTER_REGISTERED_RING so the kernel interprets ring_fd as the 
  registered index; liburing does this automatically.
claim: With IORING_ENTER_REGISTERED_RING the fd argument of io_uring_enter is 
  the registered ring offset, not a file descriptor.
kind: api
confidence: sourced
valid_for: linux>=5.18
scopes:
- layer:kernel
- tech:io-uring
aliases:
- IORING_ENTER_REGISTERED_RING
- индекс зарегистрированного кольца
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-registration
  applies_with:
  - id: f-os-io-uring-register-ring-fd
    w: 0.9
    note: the flag is meaningless without a registered ring fd
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

With IORING_ENTER_REGISTERED_RING the fd argument of io_uring_enter is the registered ring offset, not a file descriptor. [@src-man-io-uring-enter-2 гл. 2 "setting this flag will tell the kernel that the ring_fd passed in is the registered ring offset rather than a normal file descriptor"]

## Why

The kernel cannot tell an index from a descriptor without the flag.
