---
id: f-os-io-uring-link-timeout
type: fact
domain: os
title: IORING_OP_LINK_TIMEOUT bounds the linked request
summary: A link timeout (Linux 5.5) is attached after a request with 
  IOSQE_IO_LINK; it acts on that request rather than on the completion queue and
  completes with -ETIME or -ECANCELED.
claim: IORING_OP_LINK_TIMEOUT cancels the request it is linked to unless that 
  request completes first.
kind: api
confidence: sourced
valid_for: linux>=5.5
scopes:
- layer:kernel
- tech:io-uring
aliases:
- таймаут связанного запроса
- IORING_OP_LINK_TIMEOUT
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-linking
  applies_with:
  - id: f-os-io-uring-io-link-chain
    w: 0.8
    note: the timeout must directly follow the request in a link
  related:
  - f-os-io-uring-timeout-op
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_OP_LINK_TIMEOUT cancels the request it is linked to unless that request completes first. [@src-man-io-uring-enter-2 гл. 2 "Unlike IORING_OP_TIMEOUT, IORING_OP_LINK_TIMEOUT acts on the linked request, not the completion queue"]

## Why

Per-request deadlines (a recv that may never return) are otherwise impossible without cancel.
