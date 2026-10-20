---
id: f-os-io-uring-link-continues-after-error
type: fact
domain: os
title: A failed link does not affect the rest of the chain
summary: The belief that linked SQEs only share ordering and that an error in 
  one member lets the remaining chain execute normally.
claim: A failed request in an IOSQE_IO_LINK chain does not affect the linked 
  requests after it.
kind: pitfall
confidence: contested
valid_for: linux>=5.3
scopes:
- layer:kernel
- tech:io-uring
aliases:
- цепочка продолжается после ошибки
- ошибка в цепочке SQE
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - tech-io-uring
  contradicts:
  - f-os-io-uring-link-breaks-on-error
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

A failed request in an IOSQE_IO_LINK chain does not affect the linked requests after it. [@src-man-io-uring-enter-2]

## Caveats

Contradicts [[f-os-io-uring-link-breaks-on-error]].
