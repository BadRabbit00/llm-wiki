---
id: f-os-io-uring-register-buffers-waits-idle
type: fact
domain: os
title: Registering buffers waits for an idle ring (before 5.13)
summary: 'Before Linux 5.13 registering (or unregistering) buffers quiesced the ring:
  the call blocked until no request was in flight, and the only way to change the
  set was to replace it entirely.'
claim: IORING_REGISTER_BUFFERS waits for all in-flight requests to finish before
  it proceeds.
kind: pitfall
confidence: sourced
valid_for: linux>=5.1, linux<5.13
scopes:
- layer:kernel
- tech:io-uring
aliases:
- регистрация ждёт простоя кольца
- quiesce при регистрации
sources:
- src-man-io-uring-register-2
relations:
  about:
  - tech-io-uring
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_REGISTER_BUFFERS waits for all in-flight requests to finish before it proceeds. [@src-man-io-uring-register-2 гл. 2 "Note that before 5.13 registering buffers would wait for the ring to idle"]

## Caveats

Register buffers before the first submission on such kernels to avoid the stall.
