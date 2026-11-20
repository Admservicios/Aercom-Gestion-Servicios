#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--reiniciar" ) ]]; then
    printf '%s\n' "Uso: bash .devcontainer/iniciar.sh [--reiniciar]" >&2
    exit 2
fi
umask 077
mkdir -p .aercom-demo
if [[ ! -s .aercom-demo/django.key ]]; then
    python -c 'from secrets import token_hex; print(token_hex(48))' > .aercom-demo/django.key
fi
export DJANGO_SECRET_KEY="$(cat .aercom-demo/django.key)"
python manage.py migrate --noinput
esta_activo() {
    curl --noproxy 127.0.0.1 -fsS --max-time 2 http://127.0.0.1:8000/ingresar/ >/dev/null 2>&1
}

if [[ "${1:-}" == "--reiniciar" ]]; then
    while IFS= read -r proceso; do
        if [[ "$(readlink "/proc/$proceso/cwd" 2>/dev/null || true)" == "$PWD" ]]; then
            kill -TERM "$proceso"
        fi
    done < <(pgrep -u "$(id -u)" -f '(^|/)python(3([.][0-9]+)?)? manage[.]py runserver 0[.]0[.]0[.]0:8000 --noreload --insecure$' || true)
    for intento in {1..10}; do
        if ! esta_activo; then break; fi
        sleep 1
    done
    if esta_activo; then
        printf '%s\n' "El puerto 8000 sigue ocupado. No se inició otro servidor." >&2
        exit 1
    fi
else
    python manage.py cargar_demo
    if esta_activo; then exit 0; fi
fi
nohup python manage.py runserver 0.0.0.0:8000 --noreload --insecure >/tmp/aercom-piloto.log 2>&1 </dev/null &
pid=$!
for intento in {1..30}; do
    if esta_activo; then
        printf '%s\n' "Aercom Servicios está disponible en el puerto 8000."
        exit 0
    fi
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
done
cat /tmp/aercom-piloto.log >&2
exit 1
