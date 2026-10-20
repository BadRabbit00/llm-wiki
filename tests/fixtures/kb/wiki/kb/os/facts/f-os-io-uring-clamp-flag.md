---
id: f-os-io-uring-clamp-flag
type: fact
domain: os
title: IORING_SETUP_CLAMP clamps oversized entries
summary: With IORING_SETUP_CLAMP (Linux 5.6) a too-large `entries` argument is 
  reduced to IORING_MAX_ENTRIES and cq_entries to IORING_MAX_CQ_ENTRIES rather 
  than returning EINVAL.
claim: IORING_SETUP_CLAMP clamps an entries value above IORING_MAX_ENTRIES 
  instead of failing io_uring_setup.
kind: api
confidence: sourced
valid_for: linux>=5.6
scopes:
- layer:kernel
- tech:io-uring
aliases:
- IORING_SETUP_CLAMP
- ограничение размера очереди
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-setup-flags
  refines:
  - f-os-io-uring-max-entries-32768
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_SETUP_CLAMP clamps an entries value above IORING_MAX_ENTRIES instead of failing io_uring_setup. [@src-man-io-uring-setup-2 гл. 2 "if entries exceeds IORING_MAX_ENTRIES, then entries will be clamped at IORING_MAX_ENTRIES"]

## Why

Lets a program ask for a generous ring without knowing the kernel's limit.
