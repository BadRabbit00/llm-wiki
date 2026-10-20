---
id: top-os-io-uring-linking
type: topic
domain: os
title: Linked SQEs, drain and ordering
summary: 'Expressing dependencies inside a ring: IOSQE_IO_LINK chains, hard links,
  the drain barrier, link timeouts and deferred file assignment.'
priority: 4
scopes:
- layer:kernel
- tech:io-uring
aliases:
- связанные запросы
- цепочки SQE
- порядок выполнения
relations:
  builds_on:
  - top-os-io-uring-submission
  applies_with:
  - top-os-io-uring-multishot-timeouts-cancel
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Digest

Because completions are unordered, ordering must be declared. IOSQE_IO_LINK (5.3) chains an SQE to the next one so it starts only after the previous completes; an error, including a short read, cancels the rest of the chain with -ECANCELED, unless IOSQE_IO_HARDLINK (5.5) is used. IOSQE_IO_DRAIN (5.2) is a full barrier against everything submitted before and after. IORING_OP_LINK_TIMEOUT (5.5) bounds a single linked request, and since 5.17 the file of a linked request is resolved when it executes, so open-then-read chains over direct descriptors work.

## Facts

1. [[f-os-io-uring-io-link-chain]]
2. [[f-os-io-uring-link-breaks-on-error]]
3. [[f-os-io-uring-hardlink]]
4. [[f-os-io-uring-io-drain]]
5. [[f-os-io-uring-link-timeout]]
6. [[f-os-io-uring-linked-file-assignment]]
