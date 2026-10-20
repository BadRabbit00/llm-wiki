---
id: f-os-io-uring-registration-pins-resources
type: fact
domain: os
title: Registration pins resources once instead of per request
summary: io_uring_register(2) takes long-term references to files and long-term 
  mappings of buffers so that individual requests skip the per-operation lookup 
  and pinning.
claim: Registering files and buffers with io_uring_register keeps kernel 
  references and mappings alive across requests, lowering per-I/O overhead.
kind: mechanism
confidence: inferred
scopes:
- layer:kernel
- tech:io-uring
aliases:
- регистрация снижает накладные расходы
- долгоживущие ссылки
sources:
- src-man-io-uring-register-2
relations:
  about:
  - tech-io-uring
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Registering files and buffers with io_uring_register keeps kernel references and mappings alive across requests, lowering per-I/O overhead. [@src-man-io-uring-register-2]

## Caveats

Registration is a separate system call and is meant to be done once at startup.
