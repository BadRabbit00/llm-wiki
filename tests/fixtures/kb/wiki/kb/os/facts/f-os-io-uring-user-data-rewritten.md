---
id: f-os-io-uring-user-data-rewritten
type: fact
domain: os
title: The kernel rewrites user_data in the CQE
summary: The belief that the completion entry's user_data is a kernel-chosen 
  handle rather than the value the application stored in the SQE.
claim: The kernel replaces user_data in the CQE with an internal request 
  identifier of its own.
kind: mechanism
confidence: contested
scopes:
- layer:kernel
- tech:io-uring
aliases:
- user_data перезаписывается
- идентификатор запроса от ядра
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - tech-io-uring
  contradicts:
  - f-os-io-uring-user-data-roundtrip
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

The kernel replaces user_data in the CQE with an internal request identifier of its own. [@src-man-io-uring-enter-2]

## Caveats

Contradicts [[f-os-io-uring-user-data-roundtrip]].
