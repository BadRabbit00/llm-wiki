---
id: f-os-liburing-submit
type: fact
domain: os
title: 'Step 4: io_uring_submit pushes prepared SQEs to the kernel'
summary: io_uring_submit(3) publishes all SQEs taken since the last submit and 
  calls io_uring_enter(2) (or just updates the tail for SQPOLL), returning the 
  number of submitted entries.
claim: io_uring_submit(3) submits the prepared SQEs and returns how many were 
  submitted.
kind: step
confidence: sourced
scopes:
- layer:kernel
- tech:io-uring
aliases:
- отправка SQE
- io_uring_submit
sources:
- src-liburing-man-3
relations:
  about:
  - top-os-io-uring-submission
  - tech-liburing
  precedes:
  - f-os-liburing-wait-cqe
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

io_uring_submit(3) submits the prepared SQEs and returns how many were submitted. [@src-liburing-man-3 гл. 3 "submits the next events to the submission queue belonging to the ring"]

## Why

Batching several SQEs per submit is the main lever for syscall amortisation.
