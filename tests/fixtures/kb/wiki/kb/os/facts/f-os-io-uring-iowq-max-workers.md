---
id: f-os-io-uring-iowq-max-workers
type: fact
domain: os
title: IORING_REGISTER_IOWQ_MAX_WORKERS bounds async workers
summary: IORING_REGISTER_IOWQ_MAX_WORKERS (Linux 5.15) takes an array of two 
  values, the bounded and unbounded worker limits per NUMA node, and returns the
  previous values; passing 0 only queries.
claim: IORING_REGISTER_IOWQ_MAX_WORKERS sets per-ring maximums for bounded and 
  unbounded io-wq workers.
kind: api
confidence: sourced
valid_for: linux>=5.15
scopes:
- layer:kernel
- tech:io-uring
aliases:
- лимит воркеров io-wq
- IORING_REGISTER_IOWQ_MAX_WORKERS
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

IORING_REGISTER_IOWQ_MAX_WORKERS sets per-ring maximums for bounded and unbounded io-wq workers. [@src-man-io-uring-register-2 гл. 2 "Index 0 holds the bounded worker count, and index 1 holds the unbounded worker count"]

## Why

The default unbounded limit follows RLIMIT_NPROC, which may be far more threads than a service wants.
