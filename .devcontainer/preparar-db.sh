#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077
if [[ ! -s .env ]]; then
    clave=$(openssl rand -hex 32)
    (
        set -o noclobber
        printf 'POSTGRES_DB=aercom_demo\nPOSTGRES_USER=aercom_demo\nPOSTGRES_PASSWORD=%s\n' "$clave" > .env
    )
fi
