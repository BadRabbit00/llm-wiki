#!/usr/bin/env bash
set -euo pipefail
: "${LLAMA_SERVER_BIN:?Set LLAMA_SERVER_BIN in /etc/llm-wiki/llama.env}"
: "${LLAMA_ARG_MODEL:?Set LLAMA_ARG_MODEL in /etc/llm-wiki/llama.env}"
if [[ "$LLAMA_SERVER_BIN" != /* || ! -x "$LLAMA_SERVER_BIN" ]]; then
    echo 'LLAMA_SERVER_BIN must be an absolute executable path accessible to llm-model.' >&2
    exit 1
fi
if [[ "$LLAMA_ARG_MODEL" != /* || ! -r "$LLAMA_ARG_MODEL" ]]; then
    echo 'LLAMA_ARG_MODEL must be an absolute readable GGUF path accessible to llm-model.' >&2
    exit 1
fi
exec "$LLAMA_SERVER_BIN"
