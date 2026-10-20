---
id: f-os-io-uring-iopoll-requires-o-direct
type: fact
domain: os
title: IOPOLL works only with O_DIRECT descriptors
summary: Polled I/O in io_uring requires the file to be opened with O_DIRECT; 
  buffered reads and writes on an IOPOLL ring are not supported.
claim: IORING_SETUP_IOPOLL is usable only on file descriptors opened with 
  O_DIRECT.
kind: constraint
confidence: sourced
valid_for: linux>=5.1
scopes:
- layer:kernel
- tech:io-uring
aliases:
- IOPOLL только O_DIRECT
- ограничение поллинга
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-setup-flags
  refines:
  - f-os-io-uring-iopoll-busy-wait
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_SETUP_IOPOLL is usable only on file descriptors opened with O_DIRECT. [@src-man-io-uring-setup-2 гл. 2 "Currently, this feature is usable only on a file descriptor opened using the O_DIRECT flag"]

## Why

Polling bypasses the page cache completion path, which only direct I/O provides.
