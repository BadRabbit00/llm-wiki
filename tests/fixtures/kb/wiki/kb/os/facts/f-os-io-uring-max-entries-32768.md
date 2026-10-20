---
id: f-os-io-uring-max-entries-32768
type: fact
domain: os
title: The SQ may hold at most 32768 entries
summary: Since Linux 5.4 the upper bound for the SQ size requested from 
  io_uring_setup(2) is 32768 entries (IORING_MAX_ENTRIES); the CQ bound is twice
  that.
claim: IORING_MAX_ENTRIES limits io_uring_setup entries to 32768; larger values 
  fail unless clamped.
kind: number
confidence: inferred
valid_for: linux>=5.4
value: '32768'
unit: entries
scopes:
- layer:kernel
- tech:io-uring
aliases:
- максимальный размер очереди io_uring
- IORING_MAX_ENTRIES
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-ring-model
  replaces:
  - f-os-io-uring-max-entries-4096
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_MAX_ENTRIES limits io_uring_setup entries to 32768; larger values fail unless clamped. [@src-man-io-uring-setup-2]

## Why

The limit protects kernel memory; the request is rounded up to a power of two below the bound.

## Caveats

Linux 5.1-5.3 used a 4096 entry limit; IORING_SETUP_CLAMP (5.6) clamps instead of failing with EINVAL.
