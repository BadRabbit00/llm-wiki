---
id: f-os-io-uring-buffer-returns-to-pool
type: fact
domain: os
title: A used buffer returns to the pool automatically
summary: The belief that provided buffers are recycled by the kernel after each 
  completion without the application re-providing them.
claim: After a completion the kernel keeps the selected buffer in the provided 
  pool and may hand it out again.
kind: pitfall
confidence: contested
valid_for: linux>=5.7
scopes:
- layer:kernel
- tech:io-uring
aliases:
- буфер возвращается в пул сам
- автоматический возврат буфера
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - tech-io-uring
  contradicts:
  - f-os-io-uring-buffer-consumed-once
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

After a completion the kernel keeps the selected buffer in the provided pool and may hand it out again. [@src-man-io-uring-enter-2]

## Caveats

Contradicts [[f-os-io-uring-buffer-consumed-once]].
