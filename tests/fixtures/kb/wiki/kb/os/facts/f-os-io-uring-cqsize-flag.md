---
id: f-os-io-uring-cqsize-flag
type: fact
domain: os
title: IORING_SETUP_CQSIZE sizes the CQ independently
summary: By default the completion ring is twice the submission ring; 
  IORING_SETUP_CQSIZE (Linux 5.5) takes io_uring_params.cq_entries instead, 
  greater than `entries` and rounded up to the next power of two.
claim: IORING_SETUP_CQSIZE creates the CQ with cq_entries entries, which must 
  exceed entries and is rounded up to a power of two.
kind: api
confidence: sourced
valid_for: linux>=5.5
scopes:
- layer:kernel
- tech:io-uring
aliases:
- размер очереди завершений
- IORING_SETUP_CQSIZE
- cq_entries
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-ring-model
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_SETUP_CQSIZE creates the CQ with cq_entries entries, which must exceed entries and is rounded up to a power of two. [@src-man-io-uring-setup-2 гл. 2 "The value must be greater than entries, and may be rounded up to the next power-of-two"]

## Why

Multishot and provided-buffer workloads post many more completions than submissions and need a deeper CQ.
