---
id: f-os-io-uring-shared-rings
type: fact
domain: os
title: io_uring communicates through rings shared with the kernel
summary: io_uring (Linux async I/O) uses a submission ring and a completion ring
  mapped into both user space and the kernel instead of per-operation system 
  calls.
claim: io_uring submits and completes I/O through ring buffers shared between 
  user space and the kernel.
kind: mechanism
confidence: sourced
scopes:
- layer:kernel
- tech:io-uring
aliases:
- кольцевые буферы io_uring
- общая память с ядром
- SQ и CQ
sources:
- src-man-io-uring-7
relations:
  about:
  - top-os-io-uring-ring-model
  - tech-io-uring
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

io_uring submits and completes I/O through ring buffers shared between user space and the kernel. [@src-man-io-uring-7 гл. 7 "io_uring gets its name from ring buffers which are shared between user space and kernel space"]

## Why

Sharing the rings removes the copy of request descriptors on every call; the kernel reads SQEs and writes CQEs in place.

## Caveats

The rings are plain memory: without liburing the application must honour the head/tail protocol itself.
