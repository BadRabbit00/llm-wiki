---
id: f-os-io-uring-kernel-selected-buffers
type: fact
domain: os
title: The kernel selects a buffer from a provided group when data arrives
summary: IORING_OP_PROVIDE_BUFFERS gives the kernel a pool; requests marked 
  IOSQE_BUFFER_SELECT take a buffer from it only when the socket or file becomes
  readable.
claim: With provided buffers the application pre-registers a group and the 
  kernel picks one for a read or receive at the moment data is ready.
kind: mechanism
confidence: inferred
valid_for: linux>=5.7
scopes:
- layer:kernel
- tech:io-uring
aliases:
- выбор буфера при готовности
- пул буферов в ядре
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

With provided buffers the application pre-registers a group and the kernel picks one for a read or receive at the moment data is ready. [@src-man-io-uring-enter-2]

## Caveats

Buffer groups are identified by a 16-bit group ID chosen by the application.
