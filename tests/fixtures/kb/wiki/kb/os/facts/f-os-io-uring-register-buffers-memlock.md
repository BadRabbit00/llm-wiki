---
id: f-os-io-uring-register-buffers-memlock
type: fact
domain: os
title: Registered buffers are locked and charged to RLIMIT_MEMLOCK
summary: Buffers registered with IORING_REGISTER_BUFFERS are pinned for the 
  lifetime of the registration and accounted to RLIMIT_MEMLOCK, so large pools 
  need a raised limit or privileges.
claim: IORING_REGISTER_BUFFERS locks the buffers in memory and charges them 
  against the user's RLIMIT_MEMLOCK.
kind: constraint
confidence: sourced
scopes:
- layer:kernel
- tech:io-uring
aliases:
- лимит memlock
- закреплённые буферы
- IORING_REGISTER_BUFFERS
sources:
- src-man-io-uring-register-2
relations:
  about:
  - top-os-io-uring-registration
  refines:
  - f-os-io-uring-register-reduces-overhead
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_REGISTER_BUFFERS locks the buffers in memory and charges them against the user's RLIMIT_MEMLOCK. [@src-man-io-uring-register-2 гл. 2 "The buffers associated with the iovecs will be locked in memory and charged against the user's RLIMIT_MEMLOCK resource limit"]

## Why

Pinned pages cannot be swapped, so the kernel bounds them per user.

## Caveats

Buffers must be anonymous memory; huge pages are pinned entirely even if partly used.
