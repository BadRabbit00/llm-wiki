---
id: f-os-io-uring-timeout-monotonic-only
type: fact
domain: os
title: Timeouts use CLOCK_MONOTONIC only (before 5.15)
summary: Before Linux 5.15 timeout requests had a single clock source, 
  CLOCK_MONOTONIC, so wall-clock deadlines had to be converted by the 
  application.
claim: IORING_OP_TIMEOUT always measures time on CLOCK_MONOTONIC; no other clock
  can be selected.
kind: api
confidence: sourced
valid_for: linux>=5.4, linux<5.15
scopes:
- layer:kernel
- tech:io-uring
aliases:
- только CLOCK_MONOTONIC
- часы таймаута до 5.15
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

IORING_OP_TIMEOUT always measures time on CLOCK_MONOTONIC; no other clock can be selected. [@src-man-io-uring-enter-2 гл. 2 "Like IORING_OP_TIMEOUT the clock source used is CLOCK_MONOTONIC"]

## Caveats

A wall-clock deadline had to be converted to a monotonic offset at submission time.
