---
id: src-man-io-uring-register-2
type: source
title: io_uring_register(2) manual page
summary: 'Manual page of io_uring_register(2): registering buffers, files, eventfd,
  personalities, restrictions, ring fds and worker limits.'
kind: spec
url: https://man7.org/linux/man-pages/man2/io_uring_register.2.html
raw_path: raw/docs/man-io-uring-register-2.txt
raw_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
ingested_at: '2026-10-20'
covers:
- top-os-io-uring-registration
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Кратко

The io_uring_register(2) manual page (section 2) describes resource registration: fixed buffers and their accounting, fixed files and sparse updates, eventfd, personalities, restrictions, registered ring descriptors and io-wq worker limits.

## Ключевые факты

- [[f-os-io-uring-register-reduces-overhead]]: io_uring_register(2) lets the kernel keep long-term references to files and mappings of buffers, reducing per-I/O cost.
- [[f-os-io-uring-register-buffers-memlock]]: IORING_REGISTER_BUFFERS locks the buffers in memory and charges them against the user's RLIMIT_MEMLOCK.
- [[f-os-io-uring-registered-buffer-1gib-limit]]: Each buffer registered with IORING_REGISTER_BUFFERS is limited to 1 GiB in size.
- [[f-os-io-uring-files-update-sparse]]: A registered file set may contain -1 entries and IORING_REGISTER_FILES_UPDATE replaces entries without re-registering.
- [[f-os-io-uring-restrictions-allowlist]]: IORING_REGISTER_RESTRICTIONS registers an allowlist of permitted register opcodes, SQE opcodes and flags in one call.

## Что изменилось в вики

Hand-written stage-1 corpus: [[top-os-io-uring-registration]]. No raw text is stored (raw_sha256 is the SHA-256 of empty input); quotes were checked against the published text by the author.
