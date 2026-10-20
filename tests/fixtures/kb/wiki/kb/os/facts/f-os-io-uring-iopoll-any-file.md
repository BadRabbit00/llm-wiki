---
id: f-os-io-uring-iopoll-any-file
type: fact
domain: os
title: IOPOLL works with any file descriptor
summary: The belief that a polled ring can drive ordinary page-cache reads and 
  writes as well as direct I/O.
claim: IORING_SETUP_IOPOLL works with any file descriptor, including buffered 
  files opened without O_DIRECT.
kind: constraint
confidence: contested
valid_for: linux>=5.1
scopes:
- layer:kernel
- tech:io-uring
aliases:
- IOPOLL для любых файлов
- поллинг буферизованного ввода-вывода
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - tech-io-uring
  contradicts:
  - f-os-io-uring-iopoll-requires-o-direct
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_SETUP_IOPOLL works with any file descriptor, including buffered files opened without O_DIRECT. [@src-man-io-uring-setup-2]

## Caveats

Contradicts [[f-os-io-uring-iopoll-requires-o-direct]].
