---
id: f-os-io-uring-enter-getevents
type: fact
domain: os
title: IORING_ENTER_GETEVENTS waits for min_complete events
summary: The IORING_ENTER_GETEVENTS flag makes io_uring_enter(2) wait until at 
  least min_complete events sit in the CQ; without the flag the call only 
  submits.
claim: With IORING_ENTER_GETEVENTS io_uring_enter blocks until min_complete 
  completions are available.
kind: api
confidence: sourced
valid_for: linux>=5.1
scopes:
- layer:kernel
- tech:io-uring
aliases:
- IORING_ENTER_GETEVENTS
- ожидание завершений
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-submission
  refines:
  - f-os-io-uring-enter-submit-and-wait
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

With IORING_ENTER_GETEVENTS io_uring_enter blocks until min_complete completions are available. [@src-man-io-uring-enter-2 гл. 2 "the system call will wait for the specified number of events in min_complete before returning"]

## Why

min_complete is the batching knob: higher values mean fewer wakeups at the cost of latency.
