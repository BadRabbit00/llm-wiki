---
id: f-os-io-uring-linked-file-assignment
type: fact
domain: os
title: Linked requests get their file assigned at execution
summary: Since Linux 5.17 (IORING_FEAT_LINKED_FILE) a request later in a link 
  chain resolves its fd when it executes, so a direct descriptor opened by an 
  earlier link is visible to it.
claim: With IORING_FEAT_LINKED_FILE the kernel assigns the file of a linked 
  request when it starts, not at submission.
kind: mechanism
confidence: sourced
valid_for: linux>=5.17
scopes:
- layer:kernel
- tech:io-uring
aliases:
- отложенное назначение файла
- IORING_FEAT_LINKED_FILE
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-linking
  refines:
  - f-os-io-uring-io-link-chain
  replaces:
  - f-os-io-uring-link-file-assigned-upfront
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

With IORING_FEAT_LINKED_FILE the kernel assigns the file of a linked request when it starts, not at submission. [@src-man-io-uring-setup-2 гл. 2 "the kernel will defer file assignment until execution of a given request is started"]

## Why

open-then-read chains over direct descriptors need the file to exist when read starts.
