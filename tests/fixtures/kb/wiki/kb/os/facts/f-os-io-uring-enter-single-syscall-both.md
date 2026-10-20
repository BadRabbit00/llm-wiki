---
id: f-os-io-uring-enter-single-syscall-both
type: fact
domain: os
title: One syscall both submits and reaps
summary: The io_uring_enter(2) system call combines submission of new entries 
  with waiting for a number of completions, replacing separate submit and poll 
  calls.
claim: io_uring_enter lets a single system call submit pending SQEs and wait for
  completions at the same time.
kind: api
confidence: inferred
valid_for: linux>=5.1
scopes:
- layer:kernel
- tech:io-uring
aliases:
- один syscall на отправку и ожидание
- io_uring_enter
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - tech-io-uring
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

io_uring_enter lets a single system call submit pending SQEs and wait for completions at the same time. [@src-man-io-uring-enter-2]

## Caveats

With SQPOLL the submission half of the call is normally unnecessary.
