---
id: f-os-io-uring-attach-wq
type: fact
domain: os
title: IORING_SETUP_ATTACH_WQ shares the worker pool between rings
summary: With IORING_SETUP_ATTACH_WQ (Linux 5.6) and io_uring_params.wq_fd set 
  to another ring's fd, the new ring reuses that ring's io-wq thread pool 
  instead of creating its own.
claim: IORING_SETUP_ATTACH_WQ makes a new ring share the async worker backend of
  an existing ring given in wq_fd.
kind: api
confidence: sourced
valid_for: linux>=5.6
scopes:
- layer:kernel
- tech:io-uring
aliases:
- IORING_SETUP_ATTACH_WQ
- общий пул воркеров
- wq_fd
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-setup-flags
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_SETUP_ATTACH_WQ makes a new ring share the async worker backend of an existing ring given in wq_fd. [@src-man-io-uring-setup-2 гл. 2 "will share the asynchronous worker thread backend of the specified io_uring ring, rather than create a new separate thread pool"]

## Why

A ring per thread would otherwise mean a worker pool per thread.
