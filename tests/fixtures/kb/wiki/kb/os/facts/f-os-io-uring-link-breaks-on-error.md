---
id: f-os-io-uring-link-breaks-on-error
type: fact
domain: os
title: A failed link cancels the rest of the chain
summary: When any member of an IOSQE_IO_LINK chain ends in error, io_uring 
  terminates the remaining requests of that chain and posts -ECANCELED for each 
  of them.
claim: If a linked request fails, the unstarted rest of the chain completes with
  -ECANCELED.
kind: pitfall
confidence: sourced
valid_for: linux>=5.3
scopes:
- layer:kernel
- tech:io-uring
aliases:
- разрыв цепочки
- ECANCELED в цепочке
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-linking
  refines:
  - f-os-io-uring-io-link-chain
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

If a linked request fails, the unstarted rest of the chain completes with -ECANCELED. [@src-man-io-uring-enter-2 гл. 2 "If a chain of SQE links is broken, the remaining unstarted part of the chain will be terminated and completed with -ECANCELED as the error code"]

## Why

A dependent step after a failed step would operate on invalid state.

## Caveats

Any unexpected result counts as an error, including a short read.
