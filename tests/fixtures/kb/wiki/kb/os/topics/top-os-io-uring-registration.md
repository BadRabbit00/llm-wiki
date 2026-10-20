---
id: top-os-io-uring-registration
type: topic
domain: os
title: Registered files, buffers and ring resources
summary: 'io_uring_register(2): why registration cuts per-I/O cost, memlock accounting
  and the 1 GiB buffer limit, fixed files, sparse sets, restrictions, ring fds and
  worker limits.'
priority: 4
scopes:
- layer:kernel
- tech:io-uring
aliases:
- регистрация ресурсов io_uring
- fixed files и fixed buffers
- io_uring_register
relations:
  builds_on:
  - top-os-io-uring-ring-model
  applies_with:
  - top-os-io-uring-provided-buffers
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Digest

io_uring_register(2) pins resources once so each request avoids per-I/O reference and mapping work. Registered buffers are locked memory charged to RLIMIT_MEMLOCK, at most 1 GiB each, and since 5.13 can be updated in place. IOSQE_FIXED_FILE turns sqe->fd into an index of the registered file table, which may be sparse and is updated live with IORING_REGISTER_FILES_UPDATE. Restrictions give a disabled ring an opcode allowlist, IORING_REGISTER_RING_FDS (5.18) removes the fd reference from io_uring_enter(2), and IORING_REGISTER_IOWQ_MAX_WORKERS (5.15) bounds the async worker threads.

## Facts

1. [[f-os-io-uring-register-reduces-overhead]]
2. [[f-os-io-uring-register-buffers-memlock]]
3. [[f-os-io-uring-registered-buffer-1gib-limit]]
4. [[f-os-io-uring-rsrc-tags-inplace-update]]
5. [[f-os-io-uring-fixed-file-flag]]
6. [[f-os-io-uring-files-update-sparse]]
7. [[f-os-io-uring-restrictions-allowlist]]
8. [[f-os-io-uring-register-eventfd]]
9. [[f-os-io-uring-register-ring-fd]]
10. [[f-os-io-uring-enter-registered-ring]]
11. [[f-os-io-uring-iowq-max-workers]]
