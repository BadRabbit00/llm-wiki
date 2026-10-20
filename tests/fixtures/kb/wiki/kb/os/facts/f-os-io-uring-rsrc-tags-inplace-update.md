---
id: f-os-io-uring-rsrc-tags-inplace-update
type: fact
domain: os
title: Registered buffers can be updated in place since 5.13
summary: Since Linux 5.13 (IORING_FEAT_RSRC_TAGS) individual registered buffers 
  can be updated and resources tagged; before, the full set had to be 
  unregistered and registration waited for an idle ring.
claim: With IORING_FEAT_RSRC_TAGS registered buffers are updated in place 
  instead of unregistering the whole set.
kind: mechanism
confidence: sourced
valid_for: linux>=5.13
scopes:
- layer:kernel
- tech:io-uring
aliases:
- обновление буферов на месте
- IORING_FEAT_RSRC_TAGS
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-registration
  related:
  - f-os-io-uring-register-buffers-memlock
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

With IORING_FEAT_RSRC_TAGS registered buffers are updated in place instead of unregistering the whole set. [@src-man-io-uring-setup-2 гл. 2 "registered buffers can be updated in-place, whereas before the full set would have to be unregistered to update it"]

## Why

Quiescing the ring to swap one buffer is unacceptable for a server with in-flight requests.
