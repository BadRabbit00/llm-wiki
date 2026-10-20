---
id: f-os-io-uring-sqpoll-requires-fixed-files
type: fact
domain: os
title: SQPOLL requires registered files (before 5.11)
summary: Before Linux 5.11 every request on an IORING_SETUP_SQPOLL ring had to 
  use IOSQE_FIXED_FILE with a registered file table, otherwise it was errored 
  with EBADF.
claim: An SQPOLL ring can only issue I/O on registered files; requests with 
  plain fds fail with EBADF.
kind: pitfall
confidence: sourced
valid_for: linux>=5.1, linux<5.11
scopes:
- layer:kernel
- tech:io-uring
aliases:
- SQPOLL только с fixed files
- EBADF при SQPOLL
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

An SQPOLL ring can only issue I/O on registered files; requests with plain fds fail with EBADF. [@src-man-io-uring-setup-2 гл. 2 "Before version 5.11 of the Linux kernel, to successfully use this feature, the application must register a set of files to be used for IO through io_uring_register(2)"]

## Caveats

Check IORING_FEAT_SQPOLL_NONFIXED at runtime instead of hard-coding either behaviour.
