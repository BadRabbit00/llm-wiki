---
id: f-os-io-uring-nodrop-overflow
type: fact
domain: os
title: A full CQ no longer drops completions
summary: Since Linux 5.5 (IORING_FEAT_NODROP) overflowed completion events are 
  kept in kernel memory until the CQ has room; submission then fails with -EBUSY
  until the application reaps.
claim: With IORING_FEAT_NODROP the kernel buffers completions internally when 
  the CQ ring is full instead of dropping them.
kind: mechanism
confidence: sourced
valid_for: linux>=5.5
scopes:
- layer:kernel
- tech:io-uring
aliases:
- переполнение CQ
- IORING_FEAT_NODROP
- EBUSY при отправке
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-submission
  replaces:
  - f-os-io-uring-cq-overflow-drops
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

With IORING_FEAT_NODROP the kernel buffers completions internally when the CQ ring is full instead of dropping them. [@src-man-io-uring-setup-2 гл. 2 "If a completion event occurs and the CQ ring is full, the kernel stores the event internally until such a time that the CQ ring has room for more entries"]

## Why

Losing completions silently would leak requests; buffering converts the loss into back-pressure.

## Caveats

Kernels 5.1-5.4 dropped the event and bumped the CQ `dropped` counter.
