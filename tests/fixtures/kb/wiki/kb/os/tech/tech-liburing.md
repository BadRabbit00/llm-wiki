---
id: tech-liburing
type: tech
domain: os
title: liburing
summary: 'Reference C library for io_uring by its maintainer: ring setup, prep helpers
  for every opcode, submit and completion helpers, resource registration.'
category: library
adoption: evaluating
verdict: Always use it instead of raw syscalls; it encodes the barrier protocol 
  and feature probing correctly.
current_version: 2.x
homepage: https://github.com/axboe/liburing
scopes:
- layer:runtime
- tech:io-uring
aliases:
- liburing
- библиотека io_uring
relations:
  instance_of:
  - top-os-io-uring-submission
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Summary

Thin wrapper over io_uring_setup(2), io_uring_enter(2) and io_uring_register(2) with helpers `io_uring_prep_*`, `io_uring_submit`, `io_uring_wait_cqe` and the man pages that document kernel version requirements per feature.

## Our position

Evaluating together with io_uring itself; the Rust bindings used by tokio-uring wrap the same API.
