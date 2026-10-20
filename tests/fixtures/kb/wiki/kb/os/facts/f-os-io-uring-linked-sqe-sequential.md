---
id: f-os-io-uring-linked-sqe-sequential
type: fact
domain: os
title: Linked SQEs execute one after another
summary: IOSQE_IO_LINK turns consecutive SQEs into an ordered chain where each 
  request begins only after the previous one has completed.
claim: An SQE flagged IOSQE_IO_LINK makes the following SQE wait for its 
  completion before starting.
kind: mechanism
confidence: inferred
valid_for: linux>=5.3
scopes:
- layer:kernel
- tech:io-uring
aliases:
- последовательные SQE
- IOSQE_IO_LINK
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

An SQE flagged IOSQE_IO_LINK makes the following SQE wait for its completion before starting. [@src-man-io-uring-enter-2]

## Caveats

Chains of any length are allowed; only their members are serialized.
