---
id: f-os-io-uring-readv-only-before-5-6
type: fact
domain: os
title: Only vectored read and write exist (before 5.6)
summary: Linux 5.1 through 5.5 exposed file reads and writes exclusively through
  the vectored opcodes, so even a single buffer needed an iovec.
claim: io_uring offers only IORING_OP_READV and IORING_OP_WRITEV for file I/O; 
  there is no non-vectored read opcode.
kind: api
confidence: inferred
valid_for: linux>=5.1, linux<5.6
scopes:
- layer:kernel
- tech:io-uring
aliases:
- только readv и writev
- нет IORING_OP_READ
sources:
- src-liburing-man-3
relations:
  about:
  - tech-io-uring
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

io_uring offers only IORING_OP_READV and IORING_OP_WRITEV for file I/O; there is no non-vectored read opcode. [@src-liburing-man-3]

## Caveats

The iovec must stay valid until the request completes, which the single-buffer opcode avoids.
