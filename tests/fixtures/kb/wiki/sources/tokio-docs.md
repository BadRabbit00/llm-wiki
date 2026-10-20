---
id: src-tokio-docs
type: source
title: tokio crate documentation (docs.rs)
summary: Rustdoc of tokio; citation locator гл. 1 = crate root, 2 = tokio::task,
  3 = tokio::runtime, 4 = tokio::fs, 5 = tokio::select! macro.
kind: doc
url: https://docs.rs/tokio/latest/tokio/
raw_path: raw/docs/tokio-docs.txt
raw_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
ingested_at: '2026-10-20'
covers:
- top-rust-tokio-runtime
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Кратко

Rustdoc of the tokio crate on docs.rs. Citations use `гл.` as a part locator: гл. 1 = crate root page, гл. 2 = module tokio::task, гл. 3 = module tokio::runtime, гл. 4 = module tokio::fs, гл. 5 = the tokio::select! macro page.

## Ключевые факты

- [[f-rust-tokio-runtime-components]]: A tokio runtime provides an I/O driver, a task scheduler, a timer and a blocking thread pool.
- [[f-rust-tokio-multi-thread-work-stealing]]: tokio's multi-thread scheduler runs futures on a thread pool with a work-stealing strategy.
- [[f-rust-tokio-worker-threads-default-cores]]: By default the multi-thread runtime starts one worker thread per CPU core available to the process.
- [[f-rust-tokio-spawn-runs-immediately]]: A future passed to tokio::spawn starts running in the background immediately, even if the JoinHandle is never awaited.
- [[f-rust-tokio-join-handle-detach]]: Dropping a tokio JoinHandle detaches the task: it keeps running and can no longer be joined.

## Что изменилось в вики

Hand-written stage-1 corpus: [[top-rust-tokio-runtime]]. No raw text is stored (raw_sha256 is the SHA-256 of empty input); quotes were checked against the published text by the author.
