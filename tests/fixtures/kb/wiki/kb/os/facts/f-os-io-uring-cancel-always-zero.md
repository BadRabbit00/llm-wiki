---
id: f-os-io-uring-cancel-always-zero
type: fact
domain: os
title: ASYNC_CANCEL returns 0 for every request it finds
summary: The belief that a found request is always cancelled and the cancel CQE 
  never reports -EALREADY.
claim: IORING_OP_ASYNC_CANCEL completes with 0 for every request it finds, 
  whether or not that request was already running.
kind: api
confidence: contested
valid_for: linux>=5.5
scopes:
- layer:kernel
- tech:io-uring
aliases:
- отмена всегда успешна
- cancel без EALREADY
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - tech-io-uring
  contradicts:
  - f-os-io-uring-async-cancel-results
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_OP_ASYNC_CANCEL completes with 0 for every request it finds, whether or not that request was already running. [@src-man-io-uring-enter-2]

## Caveats

Contradicts [[f-os-io-uring-async-cancel-results]].
