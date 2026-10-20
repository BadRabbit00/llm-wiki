---
id: f-os-io-uring-max-entries-4096
type: fact
domain: os
title: The SQ may hold at most 4096 entries (5.1-5.3)
summary: Linux 5.1 through 5.3 capped the submission queue requested from 
  io_uring_setup(2) at 4096 entries.
claim: IORING_MAX_ENTRIES limits io_uring_setup entries to 4096; larger values 
  fail with EINVAL.
kind: number
confidence: inferred
valid_for: linux>=5.1, linux<5.4
value: '4096'
unit: entries
scopes:
- layer:kernel
- tech:io-uring
aliases:
- лимит 4096 записей
- старый IORING_MAX_ENTRIES
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - tech-io-uring
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_MAX_ENTRIES limits io_uring_setup entries to 4096; larger values fail with EINVAL. [@src-man-io-uring-setup-2]

## Caveats

Linux 5.4 raised the bound to 32768; a program written for the old limit still works unchanged.
