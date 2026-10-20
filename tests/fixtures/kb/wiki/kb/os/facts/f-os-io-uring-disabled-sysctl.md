---
id: f-os-io-uring-disabled-sysctl
type: fact
domain: os
title: kernel.io_uring_disabled can restrict or disable io_uring
summary: 'Since Linux 6.6 the sysctl kernel.io_uring_disabled limits io_uring system-wide:
  1 allows rings only to CAP_SYS_ADMIN or members of kernel.io_uring_group, 2 makes
  io_uring_setup(2) fail for everyone.'
claim: The sysctl kernel.io_uring_disabled takes 0 (enabled), 1 (only 
  CAP_SYS_ADMIN or the io_uring_group) or 2 (disabled).
kind: constraint
confidence: inferred
valid_for: linux>=6.6
scopes:
- layer:kernel
- tech:io-uring
aliases:
- отключение io_uring
- kernel.io_uring_disabled
- io_uring_group
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

The sysctl kernel.io_uring_disabled takes 0 (enabled), 1 (only CAP_SYS_ADMIN or the io_uring_group) or 2 (disabled). [@src-man-io-uring-setup-2]

## Why

Hardened hosts and container platforms restrict io_uring because of its history of privilege-escalation bugs.

## Caveats

A service that assumes io_uring must handle EPERM from io_uring_setup(2) and fall back to epoll.
