---
id: f-os-io-uring-r-disabled
type: fact
domain: os
title: IORING_SETUP_R_DISABLED starts the ring disabled
summary: A ring created with IORING_SETUP_R_DISABLED (Linux 5.10) rejects 
  submissions until IORING_REGISTER_ENABLE_RINGS; the window is meant for 
  registering restrictions.
claim: IORING_SETUP_R_DISABLED creates the ring in a disabled state where 
  restrictions can be registered but nothing submitted.
kind: api
confidence: sourced
valid_for: linux>=5.10
scopes:
- layer:kernel
- tech:io-uring
aliases:
- отключённое кольцо
- IORING_SETUP_R_DISABLED
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

IORING_SETUP_R_DISABLED creates the ring in a disabled state where restrictions can be registered but nothing submitted. [@src-man-io-uring-setup-2 гл. 2 "the io_uring ring starts in a disabled state. In this state, restrictions can be registered, but submissions are not allowed"]

## Why

Restrictions are only meaningful if they are in place before the first request can run.
