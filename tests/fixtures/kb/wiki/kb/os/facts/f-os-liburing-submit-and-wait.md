---
id: f-os-liburing-submit-and-wait
type: fact
domain: os
title: io_uring_submit_and_wait combines submit and wait
summary: "liburing's io_uring_submit_and_wait(3) merges steps 4 and 5 of the loop:
  it submits what io_uring_get_sqe(3) prepared and blocks until wait_nr completion
  events are available."
claim: io_uring_submit_and_wait(3) submits the pending SQEs and waits for 
  wait_nr completions in one call.
kind: api
confidence: sourced
valid_for: liburing
scopes:
- layer:kernel
- tech:io-uring
aliases:
- io_uring_submit_and_wait
- отправить и подождать
sources:
- src-liburing-man-3
relations:
  about:
  - top-os-io-uring-submission
  - tech-liburing
  related:
  - f-os-liburing-submit
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

io_uring_submit_and_wait(3) submits the pending SQEs and waits for wait_nr completions in one call. [@src-liburing-man-3 гл. 3 "submits the next events to the submission queue belonging to the ring and waits for wait_nr completion events"]

## Why

One io_uring_enter(2) per iteration instead of two.
