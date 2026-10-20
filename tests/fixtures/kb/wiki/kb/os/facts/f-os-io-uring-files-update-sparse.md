---
id: f-os-io-uring-files-update-sparse
type: fact
domain: os
title: Registered file sets may be sparse and updated in place
summary: IORING_REGISTER_FILES accepts -1 for empty slots; 
  IORING_REGISTER_FILES_UPDATE (Linux 5.5) fills, removes or replaces slots in 
  the live set without tearing it down.
claim: A registered file set may contain -1 entries and 
  IORING_REGISTER_FILES_UPDATE replaces entries without re-registering.
kind: api
confidence: sourced
valid_for: linux>=5.5
scopes:
- layer:kernel
- tech:io-uring
aliases:
- разреженный набор файлов
- IORING_REGISTER_FILES_UPDATE
sources:
- src-man-io-uring-register-2
relations:
  about:
  - top-os-io-uring-registration
  related:
  - f-os-io-uring-fixed-file-flag
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

A registered file set may contain -1 entries and IORING_REGISTER_FILES_UPDATE replaces entries without re-registering. [@src-man-io-uring-register-2 гл. 2 "The file set may be sparse, meaning that the fd field in the array may be set to -1"]

## Why

Servers accept and close sockets constantly; re-registering the whole table per change would stall the ring.
