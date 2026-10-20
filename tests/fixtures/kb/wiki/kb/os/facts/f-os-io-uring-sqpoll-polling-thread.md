---
id: f-os-io-uring-sqpoll-polling-thread
type: fact
domain: os
title: SQPOLL offloads submission to a kernel polling thread
summary: IORING_SETUP_SQPOLL moves submission into a kernel thread that polls 
  the SQ tail; user space just writes SQEs and bumps the tail.
claim: With SQPOLL a kernel thread watches the submission queue and issues the 
  requests, so the application needs no submission syscall.
kind: mechanism
confidence: inferred
scopes:
- layer:kernel
- tech:io-uring
aliases:
- отправка потоком ядра
- SQ polling
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - tech-io-uring
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

With SQPOLL a kernel thread watches the submission queue and issues the requests, so the application needs no submission syscall. [@src-man-io-uring-setup-2]

## Caveats

The polling thread shows up as a separate kernel task named after the ring owner.
