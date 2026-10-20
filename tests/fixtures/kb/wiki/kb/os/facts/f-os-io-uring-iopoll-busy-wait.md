---
id: f-os-io-uring-iopoll-busy-wait
type: fact
domain: os
title: IORING_SETUP_IOPOLL busy-polls for completions
summary: A ring created with IORING_SETUP_IOPOLL reaps completions by polling 
  the device rather than through IRQ notifications, trading CPU time for lower 
  latency.
claim: IORING_SETUP_IOPOLL makes the kernel busy-wait for I/O completion instead
  of waiting for an interrupt.
kind: mechanism
confidence: sourced
scopes:
- layer:kernel
- tech:io-uring
aliases:
- поллинг завершений
- IORING_SETUP_IOPOLL
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

IORING_SETUP_IOPOLL makes the kernel busy-wait for I/O completion instead of waiting for an interrupt. [@src-man-io-uring-setup-2 гл. 2 "Perform busy-waiting for an I/O completion, as opposed to getting notifications via an asynchronous IRQ (Interrupt Request)"]

## Why

For fast NVMe devices the interrupt path costs more than spinning on the completion queue.

## Caveats

The file system and block device must support polling; the application must call io_uring_enter(2) to reap.
