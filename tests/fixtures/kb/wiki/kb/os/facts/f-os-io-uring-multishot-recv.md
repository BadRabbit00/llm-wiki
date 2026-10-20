---
id: f-os-io-uring-multishot-recv
type: fact
domain: os
title: Multishot recv needs provided buffers
summary: io_uring_prep_recv_multishot(3) (Linux 6.0) arms a receive that 
  completes repeatedly; each CQE takes a buffer from a provided group, so 
  IOSQE_BUFFER_SELECT is mandatory and MSG_WAITALL is not allowed.
claim: Multishot receive posts a CQE whenever data arrives and requires 
  IOSQE_BUFFER_SELECT with a provided buffer group.
kind: api
confidence: sourced
valid_for: linux>=6.0
scopes:
- layer:kernel
- tech:io-uring
aliases:
- multishot recv
- многократный приём
sources:
- src-liburing-man-3
relations:
  about:
  - top-os-io-uring-multishot-timeouts-cancel
  - tech-liburing
  applies_with:
  - id: f-os-io-uring-buffer-select-flag
    w: 0.9
    note: multishot recv cannot use a caller buffer
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Multishot receive posts a CQE whenever data arrives and requires IOSQE_BUFFER_SELECT with a provided buffer group. [@src-liburing-man-3 гл. 3 "Multishot variants are available since kernel 6.0"]

## Why

A single caller buffer could not hold data from several completions in flight.
