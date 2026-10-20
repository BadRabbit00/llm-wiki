---
id: f-os-io-uring-cq-overflow-drops
type: fact
domain: os
title: A full CQ drops completions (before 5.5)
summary: "Linux 5.1 through 5.4 had no overflow buffering: a completion that found
  the CQ full was lost and only counted in the ring's `dropped` field."
claim: When the CQ ring is full the kernel drops the completion and increments 
  the CQ dropped counter.
kind: pitfall
confidence: inferred
valid_for: linux>=5.1, linux<5.5
scopes:
- layer:kernel
- tech:io-uring
aliases:
- потеря завершений
- счётчик dropped
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

When the CQ ring is full the kernel drops the completion and increments the CQ dropped counter. [@src-man-io-uring-setup-2]

## Caveats

On these kernels the CQ had to be sized for the worst case of outstanding requests.
