---
id: f-os-io-uring-completions-in-submission-order
type: fact
domain: os
title: Completions are posted in submission order
summary: The belief that the completion queue preserves submission order, so a 
  write followed by an fsync in one batch is applied in that order.
claim: io_uring posts completions in exactly the order the SQEs were submitted.
kind: pitfall
confidence: contested
valid_for: linux>=5.1
scopes:
- layer:kernel
- tech:io-uring
aliases:
- завершения в порядке отправки
- FIFO завершений
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - tech-io-uring
  contradicts:
  - f-os-io-uring-completions-unordered
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

io_uring posts completions in exactly the order the SQEs were submitted. [@src-man-io-uring-enter-2]

## Caveats

Contradicts [[f-os-io-uring-completions-unordered]].
