#!/usr/bin/env bash
set -euo pipefail
export AERCOM_DEMO_PASSWORD="Aercom-Demo-2026"
python manage.py migrate --noinput
python manage.py cargar_demo
nohup python manage.py runserver 0.0.0.0:8000 --noreload --insecure >/tmp/aercom-piloto.log 2>&1 </dev/null &
