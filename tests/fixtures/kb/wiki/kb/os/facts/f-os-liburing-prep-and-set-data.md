---
id: f-os-liburing-prep-and-set-data
type: fact
domain: os
title: 'Step 3: prepare the SQE and attach user_data'
summary: After io_uring_get_sqe(3) the caller prepares the operation with a 
  helper such as io_uring_prep_read(3) and stores its request token via 
  io_uring_sqe_set_data(3).
claim: Fill the SQE with an io_uring_prep_* helper and attach a token with 
  io_uring_sqe_set_data(3).
kind: step
confidence: sourced
scopes:
- layer:kernel
- tech:io-uring
aliases:
- подготовка SQE
- io_uring_sqe_set_data
- io_uring_prep_read
sources:
- src-liburing-man-3
relations:
  about:
  - top-os-io-uring-submission
  - tech-liburing
  precedes:
  - f-os-liburing-submit
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Fill the SQE with an io_uring_prep_* helper and attach a token with io_uring_sqe_set_data(3). [@src-liburing-man-3 гл. 3 "stores a user_data pointer with the submission queue entry sqe"]

## Why

Prep helpers zero the entry and set opcode, fd, address and length consistently.

## Example

```c
io_uring_prep_read(sqe, fd, buf, len, 0);
io_uring_sqe_set_data(sqe, req);
```
