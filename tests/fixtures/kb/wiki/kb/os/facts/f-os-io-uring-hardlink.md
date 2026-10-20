---
id: f-os-io-uring-hardlink
type: fact
domain: os
title: IOSQE_IO_HARDLINK keeps the chain on errors
summary: IOSQE_IO_HARDLINK (Linux 5.5) implies IOSQE_IO_LINK and keeps executing
  the chain regardless of the previous result; it still breaks if the parent 
  fails at submission.
claim: IOSQE_IO_HARDLINK links like IOSQE_IO_LINK but does not sever the chain 
  on a failed completion.
kind: api
confidence: sourced
valid_for: linux>=5.5
scopes:
- layer:kernel
- tech:io-uring
aliases:
- жёсткая связь
- IOSQE_IO_HARDLINK
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-linking
  refines:
  - f-os-io-uring-io-link-chain
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IOSQE_IO_HARDLINK links like IOSQE_IO_LINK but does not sever the chain on a failed completion. [@src-man-io-uring-enter-2 гл. 2 "Like IOSQE_IO_LINK, but it doesn't sever regardless of the completion result"]

## Why

Cleanup steps (close after a failed read) must run even when the previous step failed.
