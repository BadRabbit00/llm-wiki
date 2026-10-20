---
id: f-os-io-uring-register-eventfd
type: fact
domain: os
title: IORING_REGISTER_EVENTFD signals completions through an eventfd
summary: Registering an eventfd (Linux 5.2) lets an epoll- or thread-based loop 
  learn about io_uring completions; IORING_REGISTER_EVENTFD_ASYNC (5.6) signals 
  only completions that did not finish inline.
claim: IORING_REGISTER_EVENTFD registers an eventfd that is signalled whenever a
  completion is posted to the ring.
kind: api
confidence: sourced
valid_for: linux>=5.2
scopes:
- layer:kernel
- tech:io-uring
aliases:
- IORING_REGISTER_EVENTFD
- eventfd для завершений
- интеграция с epoll
sources:
- src-man-io-uring-register-2
relations:
  about:
  - top-os-io-uring-registration
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_REGISTER_EVENTFD registers an eventfd that is signalled whenever a completion is posted to the ring. [@src-man-io-uring-register-2 гл. 2 "an eventfd file descriptor can be registered through this operation"]

## Why

It is the bridge between a ring and an existing readiness-based event loop.
