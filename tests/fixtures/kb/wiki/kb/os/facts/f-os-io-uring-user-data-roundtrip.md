---
id: f-os-io-uring-user-data-roundtrip
type: fact
domain: os
title: user_data travels unchanged from SQE to CQE
summary: The kernel copies the 64-bit user_data of a submission entry into its 
  completion entry, so the application uses it to match completions to requests.
claim: The user_data field of an SQE is copied verbatim into the CQE of its 
  completion.
kind: mechanism
confidence: sourced
scopes:
- layer:kernel
- tech:io-uring
aliases:
- user_data в CQE
- сопоставление запроса и завершения
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-ring-model
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

The user_data field of an SQE is copied verbatim into the CQE of its completion. [@src-man-io-uring-enter-2 гл. 2 "user_data is copied from the field of the same name in the submission queue entry"]

## Why

Completions are unordered, so a stable token is the only way to find the originating request.

## Caveats

Neither io_uring_get_sqe(3) nor the prep helpers set user_data; set it explicitly.
