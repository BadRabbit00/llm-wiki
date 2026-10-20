---
id: tech-io-uring
type: tech
domain: os
title: io_uring
summary: Linux asynchronous I/O interface (since 5.1) based on submission and 
  completion rings shared with the kernel; covers file, network, timer and 
  cancellation requests.
category: protocol
adoption: evaluating
verdict: Candidate for storage and network paths above 100k ops/s per core on 
  Linux 5.19+; not adopted until measured against epoll on our workload, and an 
  epoll fallback is mandatory.
homepage: https://kernel.dk/io_uring.pdf
scopes:
- layer:kernel
aliases:
- io_uring
- асинхронный ввод-вывод Linux
- io-uring
relations:
  instance_of:
  - top-os-io-uring-ring-model
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Summary

Kernel interface for asynchronous I/O: file, network, timers, cancellation and registered resources in one ring-based API. Features appear per kernel version, so the first supporting kernel matters for every flag and opcode.

## Our position

Evaluating: the API is stable, but hardened and container hosts may restrict it with `kernel.io_uring_disabled`, so a service must fall back to epoll.
