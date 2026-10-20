---
id: f-os-io-uring-timeout-realtime-clock
type: fact
domain: os
title: Timeouts can use CLOCK_REALTIME or CLOCK_BOOTTIME since 5.15
summary: Timeout requests default to CLOCK_MONOTONIC; the flags 
  IORING_TIMEOUT_REALTIME and IORING_TIMEOUT_BOOTTIME (Linux 5.15) switch the 
  clock source for absolute deadlines.
claim: Since Linux 5.15 IORING_TIMEOUT_REALTIME and IORING_TIMEOUT_BOOTTIME 
  select the clock of a timeout request.
kind: api
confidence: inferred
valid_for: linux>=5.15
scopes:
- layer:kernel
- tech:io-uring
aliases:
- часы таймаута
- IORING_TIMEOUT_REALTIME
- IORING_TIMEOUT_BOOTTIME
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-multishot-timeouts-cancel
  refines:
  - f-os-io-uring-timeout-op
  replaces:
  - f-os-io-uring-timeout-monotonic-only
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Since Linux 5.15 IORING_TIMEOUT_REALTIME and IORING_TIMEOUT_BOOTTIME select the clock of a timeout request. [@src-man-io-uring-enter-2]

## Why

Wall-clock deadlines (cron-like jobs) cannot be expressed on a monotonic clock.
