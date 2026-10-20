---
id: f-os-io-uring-io-drain
type: fact
domain: os
title: IOSQE_IO_DRAIN is a barrier in the submission stream
summary: 'An SQE with IOSQE_IO_DRAIN (Linux 5.2) acts as a full barrier: it starts
  after every previously submitted request finished, and nothing submitted after it
  starts before it completes.'
claim: IOSQE_IO_DRAIN waits for all earlier SQEs to complete and blocks later 
  SQEs until it completes.
kind: api
confidence: sourced
valid_for: linux>=5.2
scopes:
- layer:kernel
- tech:io-uring
aliases:
- барьер IOSQE_IO_DRAIN
- дренаж очереди
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-linking
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IOSQE_IO_DRAIN waits for all earlier SQEs to complete and blocks later SQEs until it completes. [@src-man-io-uring-enter-2 гл. 2 "the SQE will not be started before previously submitted SQEs have completed, and new SQEs will not be started before this one completes"]

## Why

A drain is the coarse tool; links are cheaper when only a few requests depend on each other.
