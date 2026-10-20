---
id: f-os-io-uring-sqpoll-nonfixed-files
type: fact
domain: os
title: SQPOLL no longer requires registered files
summary: IORING_FEAT_SQPOLL_NONFIXED (Linux 5.11) means requests on an 
  IORING_SETUP_SQPOLL ring may use normal fds; before that only IOSQE_FIXED_FILE
  indexes worked.
claim: Since Linux 5.11 an SQPOLL ring accepts ordinary file descriptors, not 
  only registered files.
kind: api
confidence: sourced
valid_for: linux>=5.11
scopes:
- layer:kernel
- tech:io-uring
aliases:
- SQPOLL без fixed files
- IORING_FEAT_SQPOLL_NONFIXED
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-setup-flags
  refines:
  - f-os-io-uring-sqpoll-kernel-thread
  replaces:
  - f-os-io-uring-sqpoll-requires-fixed-files
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Since Linux 5.11 an SQPOLL ring accepts ordinary file descriptors, not only registered files. [@src-man-io-uring-setup-2 гл. 2 "the IORING_SETUP_SQPOLL feature no longer requires the use of fixed files. Any normal file descriptor can be used for IO commands without needing registration"]

## Why

The kernel thread now runs in the context of the owning task and can resolve its file table.
