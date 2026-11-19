#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
mkdir -p .aercom-demo
if [[ ! -s .aercom-demo/django.key ]]; then
    python -c 'from secrets import token_hex; print(token_hex(48))' > .aercom-demo/django.key
fi
export DJANGO_SECRET_KEY="$(cat .aercom-demo/django.key)"
python manage.py migrate --noinput
python manage.py cargar_demo
if curl --noproxy 127.0.0.1 -fsS --max-time 2 http://127.0.0.1:8000/ingresar/ >/dev/null 2>&1; then
    exit 0
fi
nohup python manage.py runserver 0.0.0.0:8000 --noreload --insecure >/tmp/aercom-piloto.log 2>&1 </dev/null &
pid=$!
for intento in {1..30}; do
    if curl --noproxy 127.0.0.1 -fsS --max-time 2 http://127.0.0.1:8000/ingresar/ >/dev/null 2>&1; then
        exit 0
    fi
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
done
cat /tmp/aercom-piloto.log >&2
exit 1
