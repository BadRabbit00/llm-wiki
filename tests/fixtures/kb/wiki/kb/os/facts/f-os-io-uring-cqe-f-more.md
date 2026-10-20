---
id: f-os-io-uring-cqe-f-more
type: fact
domain: os
title: IORING_CQE_F_MORE says a multishot request stays armed
summary: 'For multishot accept, receive and poll the application checks IORING_CQE_F_MORE
  on each CQE: when the flag is missing the request has terminated and must be submitted
  again.'
claim: A multishot completion carries IORING_CQE_F_MORE while the request will 
  produce further CQEs; its absence means re-arm.
kind: mechanism
confidence: sourced
scopes:
- layer:kernel
- tech:io-uring
aliases:
- IORING_CQE_F_MORE
- признак продолжения multishot
sources:
- src-liburing-man-3
relations:
  about:
  - top-os-io-uring-multishot-timeouts-cancel
  applies_with:
  - id: f-os-io-uring-multishot-accept
    w: 0.8
    note: check F_MORE on every accept completion
  - id: f-os-io-uring-multishot-recv
    w: 0.8
    note: a recv CQE without F_MORE ends the multishot
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

A multishot completion carries IORING_CQE_F_MORE while the request will produce further CQEs; its absence means re-arm. [@src-liburing-man-3 гл. 3 "the application should look at the CQE flags and see if IORING_CQE_F_MORE is set on completion as an indication of whether or not the accept request will generate further CQEs"]

## Why

Errors and buffer exhaustion silently disarm a multishot request; the flag is the only signal.
