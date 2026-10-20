---
id: f-os-io-uring-cqe-skip-success
type: fact
domain: os
title: IOSQE_CQE_SKIP_SUCCESS suppresses successful CQEs
summary: Setting IOSQE_CQE_SKIP_SUCCESS (Linux 5.17) on an SQE tells io_uring 
  not to post a completion when the request succeeds, which saves CQ space for 
  fire-and-forget requests.
claim: IOSQE_CQE_SKIP_SUCCESS omits the CQE of a request that completes 
  successfully; failures still post one.
kind: api
confidence: sourced
valid_for: linux>=5.17
scopes:
- layer:kernel
- tech:io-uring
aliases:
- пропуск CQE при успехе
- IOSQE_CQE_SKIP_SUCCESS
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-submission
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IOSQE_CQE_SKIP_SUCCESS omits the CQE of a request that completes successfully; failures still post one. [@src-man-io-uring-enter-2 гл. 2 "Don't generate a CQE if the request completes successfully"]

## Why

Link chains with many intermediate steps otherwise flood the CQ with uninteresting completions.
