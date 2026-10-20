---
id: f-os-io-uring-multishot-accept
type: fact
domain: os
title: Multishot accept posts a CQE per incoming connection
summary: io_uring_prep_multishot_accept(3) (Linux 5.19) arms one accept that 
  repeatedly triggers a completion as connections arrive, until it is cancelled 
  or fails.
claim: A multishot accept request keeps posting a CQE for every incoming 
  connection from a single submission.
kind: api
confidence: sourced
valid_for: linux>=5.19
scopes:
- layer:kernel
- tech:io-uring
aliases:
- multishot accept
- многократный accept
- IORING_ACCEPT_MULTISHOT
sources:
- src-liburing-man-3
relations:
  about:
  - top-os-io-uring-multishot-timeouts-cancel
  - tech-liburing
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

A multishot accept request keeps posting a CQE for every incoming connection from a single submission. [@src-liburing-man-3 гл. 3 "The multishot variants are available since 5.19"]

## Why

One submission per connection was the main per-connection cost of an io_uring accept loop.
