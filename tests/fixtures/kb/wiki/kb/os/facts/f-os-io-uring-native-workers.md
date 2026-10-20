---
id: f-os-io-uring-native-workers
type: fact
domain: os
title: Async helpers run as native worker threads
summary: IORING_FEAT_NATIVE_WORKERS (Linux 5.12) reports that blocking requests 
  are offloaded to io-wq workers that look like regular threads of the owning 
  process, replacing the older kernel-thread design.
claim: Since Linux 5.12 io_uring async work runs on native worker threads of the
  process rather than identity-assuming kernel threads.
kind: mechanism
confidence: sourced
valid_for: linux>=5.12
scopes:
- layer:kernel
- tech:io-uring
aliases:
- io-wq воркеры
- IORING_FEAT_NATIVE_WORKERS
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-submission
  replaces:
  - f-os-io-uring-identity-kernel-threads
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Since Linux 5.12 io_uring async work runs on native worker threads of the process rather than identity-assuming kernel threads. [@src-man-io-uring-setup-2 гл. 2 "Previous kernels used kernel threads that assumed the identity of the original io_uring owning task, but later kernels will actively create what looks more like regular process threads instead"]

## Why

Native workers inherit credentials and limits naturally and show up under the process in ps.
