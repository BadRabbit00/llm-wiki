---
id: f-os-io-uring-no-completion-ordering
type: fact
domain: os
title: No ordering between completions of independent requests
summary: 'io_uring gives no completion-order guarantee for unlinked requests: an fsync
  submitted after a write can complete before the write reaches the device.'
claim: Independent io_uring requests may complete in a different order than they
  were submitted.
kind: pitfall
confidence: inferred
valid_for: linux>=5.1
scopes:
- layer:kernel
- tech:io-uring
aliases:
- завершения не упорядочены
- порядок fsync и write
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

Independent io_uring requests may complete in a different order than they were submitted. [@src-man-io-uring-enter-2]

## Caveats

Applications that need ordering declare it per request rather than relying on the queue.
