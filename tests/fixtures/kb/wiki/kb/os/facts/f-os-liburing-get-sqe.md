---
id: f-os-liburing-get-sqe
type: fact
domain: os
title: 'Step 2: io_uring_get_sqe takes the next free SQE'
summary: io_uring_get_sqe(3) hands out a pointer to the next available SQE of 
  the ring; it returns NULL when the submission queue is full, which the caller 
  must check.
claim: io_uring_get_sqe(3) returns the next free submission entry or NULL when 
  the SQ is full.
kind: step
confidence: sourced
scopes:
- layer:kernel
- tech:io-uring
aliases:
- получить SQE
- io_uring_get_sqe
sources:
- src-liburing-man-3
relations:
  about:
  - top-os-io-uring-submission
  - tech-liburing
  precedes:
  - f-os-liburing-prep-and-set-data
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

io_uring_get_sqe(3) returns the next free submission entry or NULL when the SQ is full. [@src-liburing-man-3 гл. 3 "gets the next available submission queue entry from the submission queue belonging to the ring param"]

## Why

SQEs live in the shared array; the library only advances a local tail until submit.

## Caveats

A NULL return means submit first to free slots; ignoring it dereferences NULL.
