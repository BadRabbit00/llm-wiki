---
id: f-os-io-uring-cancel-all-fd-any
type: fact
domain: os
title: Cancel flags match all requests, by fd or any
summary: Since Linux 5.19 io_uring_prep_cancel(3) accepts 
  IORING_ASYNC_CANCEL_ALL (every match, not only the first), _FD (match on fd 
  instead of user_data) and _ANY (every pending request).
claim: IORING_ASYNC_CANCEL_ALL, _FD and _ANY cancel every matching request, 
  match by file descriptor or match everything.
kind: api
confidence: sourced
valid_for: linux>=5.19
scopes:
- layer:kernel
- tech:io-uring
aliases:
- отменить все запросы
- IORING_ASYNC_CANCEL_ALL
- IORING_ASYNC_CANCEL_FD
sources:
- src-liburing-man-3
relations:
  about:
  - top-os-io-uring-multishot-timeouts-cancel
  - tech-liburing
  refines:
  - f-os-io-uring-async-cancel-results
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_ASYNC_CANCEL_ALL, _FD and _ANY cancel every matching request, match by file descriptor or match everything. [@src-liburing-man-3 гл. 3 "Cancel all requests that match the given criteria, rather than just canceling the first one found"]

## Why

Closing a connection means cancelling every request on its fd; one cancel per request was too slow.
