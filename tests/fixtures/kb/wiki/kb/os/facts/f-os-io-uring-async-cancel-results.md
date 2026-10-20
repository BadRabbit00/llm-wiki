---
id: f-os-io-uring-async-cancel-results
type: fact
domain: os
title: IORING_OP_ASYNC_CANCEL reports 0, -ENOENT or -EALREADY
summary: 'Cancelling by user_data (Linux 5.5) yields three outcomes in the cancel
  CQE: 0 (cancelled), -ENOENT (no such request) or -EALREADY (found and in progress,
  may still complete).'
claim: IORING_OP_ASYNC_CANCEL completes with 0 when it cancelled, -ENOENT when 
  not found and -EALREADY when the request was already running.
kind: api
confidence: sourced
valid_for: linux>=5.5
scopes:
- layer:kernel
- tech:io-uring
aliases:
- отмена запроса
- IORING_OP_ASYNC_CANCEL
- EALREADY
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-multishot-timeouts-cancel
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_OP_ASYNC_CANCEL completes with 0 when it cancelled, -ENOENT when not found and -EALREADY when the request was already running. [@src-man-io-uring-enter-2 гл. 2 "If found, the res field of the cqe will contain 0. If not found, res will contain -ENOENT. If found and attempted canceled, the res field will contain -EALREADY"]

## Why

The original request still posts its own CQE (usually -ECANCELED); the cancel CQE only reports the attempt.

## Caveats

Disk I/O that already started cannot be cancelled; interruptible socket I/O can.
