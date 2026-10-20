---
id: f-os-io-uring-fixed-buffers-pinned-memlock
type: fact
domain: os
title: Fixed buffers are pinned and count toward memlock
summary: Registering buffers through IORING_REGISTER_BUFFERS locks their pages 
  in memory for the registration lifetime and charges the user's RLIMIT_MEMLOCK 
  limit.
claim: Buffers registered as fixed buffers are pinned in RAM and accounted 
  against RLIMIT_MEMLOCK.
kind: constraint
confidence: inferred
scopes:
- layer:kernel
- tech:io-uring
aliases:
- pinned buffers
- memlock и fixed buffers
sources:
- src-man-io-uring-register-2
relations:
  about:
  - tech-io-uring
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Buffers registered as fixed buffers are pinned in RAM and accounted against RLIMIT_MEMLOCK. [@src-man-io-uring-register-2]

## Caveats

ulimit -l shows the limit that applies to the registering user.
