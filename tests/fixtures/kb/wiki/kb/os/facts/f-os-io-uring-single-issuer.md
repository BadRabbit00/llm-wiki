---
id: f-os-io-uring-single-issuer
type: fact
domain: os
title: IORING_SETUP_SINGLE_ISSUER promises one submitting task
summary: Setting IORING_SETUP_SINGLE_ISSUER (Linux 6.0) enables internal 
  optimisations by promising that a single thread submits; the kernel enforces 
  it and returns -EEXIST otherwise.
claim: IORING_SETUP_SINGLE_ISSUER tells the kernel that one task submits; 
  violating it fails the request with -EEXIST.
kind: api
confidence: sourced
valid_for: linux>=6.0
scopes:
- layer:kernel
- tech:io-uring
aliases:
- единственный отправитель
- IORING_SETUP_SINGLE_ISSUER
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

IORING_SETUP_SINGLE_ISSUER tells the kernel that one task submits; violating it fails the request with -EEXIST. [@src-man-io-uring-setup-2 гл. 2 "A hint to the kernel that only a single task (or thread) will submit requests, which is used for internal optimisations"]

## Why

Without concurrent submitters the kernel can drop locking on the submission path.

## Caveats

With SQPOLL the polling thread counts as the single issuer regardless of how many user threads enter.
