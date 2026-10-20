---
id: f-os-io-uring-setup-syscall-allocates-queues
type: fact
domain: os
title: io_uring_setup allocates the queues and hands back an fd
summary: Calling io_uring_setup(2) with the desired entry count creates a ring 
  instance in the kernel and returns a file descriptor for mapping and later 
  calls.
claim: The io_uring_setup system call allocates the submission and completion 
  queues and returns the fd of the new instance.
kind: api
confidence: inferred
valid_for: linux>=5.1
scopes:
- layer:kernel
- tech:io-uring
aliases:
- системный вызов io_uring_setup
- дескриптор кольца
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

The io_uring_setup system call allocates the submission and completion queues and returns the fd of the new instance. [@src-man-io-uring-setup-2]

## Caveats

Closing that descriptor tears the instance down once all mappings are gone.
