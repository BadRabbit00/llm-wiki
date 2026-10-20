---
id: f-os-io-uring-link-file-assigned-upfront
type: fact
domain: os
title: Linked requests get their file at submission (before 5.17)
summary: Before IORING_FEAT_LINKED_FILE (Linux 5.17) io_uring prepared the file 
  for each linked request upfront, so a direct descriptor opened by an earlier 
  link was not visible to a later one.
claim: The file of every request in a link chain is resolved at submission time,
  before earlier links run.
kind: mechanism
confidence: sourced
valid_for: linux>=5.3, linux<5.17
scopes:
- layer:kernel
- tech:io-uring
aliases:
- файл назначается при отправке
- цепочка open-read до 5.17
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

The file of every request in a link chain is resolved at submission time, before earlier links run. [@src-man-io-uring-setup-2 гл. 2 "kernels without this flag will prepare the file for each link upfront"]

## Caveats

An open-then-read chain over direct descriptors had to be split into two submissions.
