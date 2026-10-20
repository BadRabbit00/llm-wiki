---
id: f-os-io-uring-sqpoll-never-sleeps
type: fact
domain: os
title: The SQPOLL thread never needs a wakeup
summary: The belief that an SQPOLL ring makes io_uring_enter(2) entirely 
  unnecessary because the polling thread never stops watching the queue.
claim: The SQPOLL kernel thread polls the submission queue forever, so the 
  application never has to call io_uring_enter.
kind: mechanism
confidence: contested
scopes:
- layer:kernel
- tech:io-uring
aliases:
- SQPOLL без пробуждения
- поток SQPOLL не спит
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - tech-io-uring
  contradicts:
  - f-os-io-uring-sqpoll-idle-wakeup
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

The SQPOLL kernel thread polls the submission queue forever, so the application never has to call io_uring_enter. [@src-man-io-uring-setup-2]

## Caveats

Contradicts [[f-os-io-uring-sqpoll-idle-wakeup]].
