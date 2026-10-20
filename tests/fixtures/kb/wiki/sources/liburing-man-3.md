---
id: src-liburing-man-3
type: source
title: liburing manual pages (section 3)
summary: 'liburing API manual pages (section 3): io_uring_queue_init, io_uring_get_sqe,
  io_uring_prep_*, io_uring_submit, io_uring_wait_cqe, registration helpers.'
kind: doc
url: https://github.com/axboe/liburing/tree/master/man
raw_path: raw/docs/liburing-man-3.txt
raw_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
ingested_at: '2026-10-20'
covers:
- top-os-io-uring-submission
- top-os-io-uring-provided-buffers
- top-os-io-uring-multishot-timeouts-cancel
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Кратко

The section 3 manual pages shipped with liburing document the library API: ring setup and teardown, SQE acquisition and preparation helpers, submission and completion helpers, resource registration, and the kernel version each feature needs.

## Ключевые факты

- [[f-os-io-uring-prep-read-since-5-6]]: io_uring_prep_read(3) prepares a non-vectored IORING_OP_READ, available since Linux 5.6.
- [[f-os-liburing-queue-init]]: io_uring_queue_init(3) calls io_uring_setup(2) and maps the rings into a struct io_uring.
- [[f-os-liburing-get-sqe]]: io_uring_get_sqe(3) returns the next free submission entry or NULL when the SQ is full.
- [[f-os-liburing-prep-and-set-data]]: Fill the SQE with an io_uring_prep_* helper and attach a token with io_uring_sqe_set_data(3).
- [[f-os-liburing-submit]]: io_uring_submit(3) submits the prepared SQEs and returns how many were submitted.

## Что изменилось в вики

Hand-written stage-1 corpus: [[top-os-io-uring-submission]], [[top-os-io-uring-provided-buffers]], [[top-os-io-uring-multishot-timeouts-cancel]]. No raw text is stored (raw_sha256 is the SHA-256 of empty input); quotes were checked against the published text by the author.
