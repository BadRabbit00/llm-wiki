---
id: f-os-io-uring-polled-completion-mode
type: fact
domain: os
title: Polled mode spins instead of taking interrupts
summary: A polled io_uring ring (IORING_SETUP_IOPOLL) checks the device 
  completion queue in a busy loop instead of being notified by an IRQ.
claim: In IOPOLL mode the kernel spins on the device for completions rather than
  relying on interrupts.
kind: mechanism
confidence: inferred
scopes:
- layer:kernel
- tech:io-uring
aliases:
- режим поллинга
- без прерываний
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

In IOPOLL mode the kernel spins on the device for completions rather than relying on interrupts. [@src-man-io-uring-setup-2]

## Caveats

Polling pays off only on devices whose completion latency is below the interrupt cost.
