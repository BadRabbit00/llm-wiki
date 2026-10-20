---
id: src-man-io-uring-enter-2
type: source
title: io_uring_enter(2) manual page
summary: 'Manual page of io_uring_enter(2): submission and completion, IORING_ENTER_*
  flags, IOSQE_* flags, opcodes and CQE semantics.'
kind: spec
url: https://man7.org/linux/man-pages/man2/io_uring_enter.2.html
raw_path: raw/docs/man-io-uring-enter-2.txt
raw_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
ingested_at: '2026-10-20'
covers:
- top-os-io-uring-ring-model
- top-os-io-uring-submission
- top-os-io-uring-setup-flags
- top-os-io-uring-linking
- top-os-io-uring-registration
- top-os-io-uring-provided-buffers
- top-os-io-uring-multishot-timeouts-cancel
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Кратко

The io_uring_enter(2) manual page (section 2) covers the submit/wait system call, the IORING_ENTER_* flags, the per-SQE IOSQE_* flags, every opcode with its first kernel version, and how results and errors are reported in the CQE.

## Ключевые факты

- [[f-os-io-uring-user-data-roundtrip]]: The user_data field of an SQE is copied verbatim into the CQE of its completion.
- [[f-os-io-uring-cqe-res-negative-errno]]: The CQE res field holds the operation result or a negative errno value on failure.
- [[f-os-io-uring-enter-submit-and-wait]]: One io_uring_enter(2) call can both submit new SQEs and wait for completions of earlier ones.
- [[f-os-io-uring-enter-getevents]]: With IORING_ENTER_GETEVENTS io_uring_enter blocks until min_complete completions are available.
- [[f-os-io-uring-completions-unordered]]: io_uring starts requests in submission order but completes them in any order; a later fsync may finish before an earlier write.

## Что изменилось в вики

Hand-written stage-1 corpus: [[top-os-io-uring-ring-model]], [[top-os-io-uring-submission]], [[top-os-io-uring-setup-flags]], [[top-os-io-uring-linking]], [[top-os-io-uring-registration]], [[top-os-io-uring-provided-buffers]], [[top-os-io-uring-multishot-timeouts-cancel]]. No raw text is stored (raw_sha256 is the SHA-256 of empty input); quotes were checked against the published text by the author.
