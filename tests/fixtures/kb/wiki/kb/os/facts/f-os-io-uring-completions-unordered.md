---
id: f-os-io-uring-completions-unordered
type: fact
domain: os
title: Completions arrive in any order
summary: 'Requests on a ring run concurrently: submission order is not completion
  order, so a write followed by an fsync in the same batch gives no durability guarantee
  unless they are linked.'
claim: io_uring starts requests in submission order but completes them in any 
  order; a later fsync may finish before an earlier write.
kind: pitfall
confidence: sourced
valid_for: linux>=5.1
scopes:
- layer:kernel
- tech:io-uring
aliases:
- порядок завершений
- fsync после write
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-submission
  applies_with:
  - id: f-os-io-uring-io-link-chain
    w: 0.9
    note: serialize write then fsync with IOSQE_IO_LINK
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

io_uring starts requests in submission order but completes them in any order; a later fsync may finish before an earlier write. [@src-man-io-uring-enter-2 гл. 2 "while I/O is initiated in the order in which it appears in the submission queue, completions are unordered"]

## Why

Each SQE is an independent request; the kernel has no implicit dependency between them.
