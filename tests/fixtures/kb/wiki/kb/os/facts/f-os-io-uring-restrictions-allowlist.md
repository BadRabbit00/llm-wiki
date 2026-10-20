---
id: f-os-io-uring-restrictions-allowlist
type: fact
domain: os
title: IORING_REGISTER_RESTRICTIONS installs an opcode allowlist
summary: On a ring started with IORING_SETUP_R_DISABLED, 
  IORING_REGISTER_RESTRICTIONS (Linux 5.10) submits all restrictions at once; 
  anything not listed is denied after the ring is enabled.
claim: IORING_REGISTER_RESTRICTIONS registers an allowlist of permitted register
  opcodes, SQE opcodes and flags in one call.
kind: api
confidence: sourced
valid_for: linux>=5.10
scopes:
- layer:kernel
- tech:io-uring
aliases:
- ограничения кольца
- IORING_REGISTER_RESTRICTIONS
- allowlist опкодов
sources:
- src-man-io-uring-register-2
relations:
  about:
  - top-os-io-uring-registration
  applies_with:
  - id: f-os-io-uring-r-disabled
    w: 0.9
    note: restrictions can only be registered on a disabled ring
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_REGISTER_RESTRICTIONS registers an allowlist of permitted register opcodes, SQE opcodes and flags in one call. [@src-man-io-uring-register-2 гл. 2 "they are handled as an allowlist (opcodes and flags not registered, are not allowed)"]

## Why

A sandboxed process can be handed a ring that only allows read and write, similar to seccomp for io_uring.
