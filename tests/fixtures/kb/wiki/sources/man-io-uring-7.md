---
id: src-man-io-uring-7
type: source
title: io_uring(7) overview manual page
summary: 'Overview manual page io_uring(7): shared rings, SQE and CQE, the submission
  and completion model.'
kind: spec
url: https://man7.org/linux/man-pages/man7/io_uring.7.html
raw_path: raw/docs/man-io-uring-7.txt
raw_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
ingested_at: '2026-10-20'
covers:
- top-os-io-uring-ring-model
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Кратко

The io_uring(7) overview page (section 7) explains the ring model: why the interface is named after its shared ring buffers, how submission and completion entries flow between user space and the kernel, and which system calls drive them.

## Ключевые факты

- [[f-os-io-uring-shared-rings]]: io_uring submits and completes I/O through ring buffers shared between user space and the kernel.

## Что изменилось в вики

Hand-written stage-1 corpus: [[top-os-io-uring-ring-model]]. No raw text is stored (raw_sha256 is the SHA-256 of empty input); quotes were checked against the published text by the author.
