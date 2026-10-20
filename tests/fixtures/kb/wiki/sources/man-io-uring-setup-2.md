---
id: src-man-io-uring-setup-2
type: source
title: io_uring_setup(2) manual page
summary: 'Manual page of io_uring_setup(2): ring creation, struct io_uring_params,
  IORING_SETUP_* flags and IORING_FEAT_* feature bits.'
kind: spec
url: https://man7.org/linux/man-pages/man2/io_uring_setup.2.html
raw_path: raw/docs/man-io-uring-setup-2.txt
raw_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
ingested_at: '2026-10-20'
covers:
- top-os-io-uring-ring-model
- top-os-io-uring-setup-flags
- top-os-io-uring-submission
- top-os-io-uring-linking
- top-os-io-uring-registration
- top-os-io-uring-multishot-timeouts-cancel
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Кратко

The io_uring_setup(2) manual page (liburing man pages, section 2) describes ring creation, struct io_uring_params, every IORING_SETUP_* flag with the kernel version that introduced it, and the IORING_FEAT_* bits the kernel reports back.

## Ключевые факты

- [[f-os-io-uring-setup-returns-fd]]: io_uring_setup(2) creates an SQ and a CQ with at least the requested entries and returns a file descriptor.
- [[f-os-io-uring-single-mmap-feature]]: With IORING_FEAT_SINGLE_MMAP the SQ and CQ rings share one mmap call; the SQE array is still mapped separately.
- [[f-os-io-uring-sqe-64-bytes]]: A submission queue entry is 64 bytes; IORING_SETUP_SQE128 switches the ring to 128-byte entries.
- [[f-os-io-uring-iopoll-busy-wait]]: IORING_SETUP_IOPOLL makes the kernel busy-wait for I/O completion instead of waiting for an interrupt.
- [[f-os-io-uring-iopoll-requires-o-direct]]: IORING_SETUP_IOPOLL is usable only on file descriptors opened with O_DIRECT.

## Что изменилось в вики

Hand-written stage-1 corpus: [[top-os-io-uring-ring-model]], [[top-os-io-uring-setup-flags]], [[top-os-io-uring-submission]], [[top-os-io-uring-linking]], [[top-os-io-uring-registration]], [[top-os-io-uring-multishot-timeouts-cancel]]. No raw text is stored (raw_sha256 is the SHA-256 of empty input); quotes were checked against the published text by the author.
