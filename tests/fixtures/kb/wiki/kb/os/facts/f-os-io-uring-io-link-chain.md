---
id: f-os-io-uring-io-link-chain
type: fact
domain: os
title: IOSQE_IO_LINK chains SQEs so the next starts after this one
summary: Setting IOSQE_IO_LINK (Linux 5.3) forms a chain whose members execute 
  sequentially; the chain ends at the first SQE without the flag, and 
  independent chains still run in parallel.
claim: IOSQE_IO_LINK links an SQE to the next one; the next request starts only 
  after this one completes.
kind: mechanism
confidence: sourced
valid_for: linux>=5.3
scopes:
- layer:kernel
- tech:io-uring
aliases:
- связанные SQE
- IOSQE_IO_LINK
- цепочка запросов
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-linking
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IOSQE_IO_LINK links an SQE to the next one; the next request starts only after this one completes. [@src-man-io-uring-enter-2 гл. 2 "That next SQE will not be started before this one completes"]

## Why

Dependencies such as write-then-fsync or accept-then-read need ordering without a round trip to user space.
