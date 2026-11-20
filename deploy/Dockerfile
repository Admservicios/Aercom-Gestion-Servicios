# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./
COPY deploy/requirements.txt deploy/requirements.txt
RUN --mount=type=secret,id=pip_ca \
    if [ -f /run/secrets/pip_ca ]; then export PIP_CERT=/run/secrets/pip_ca; fi; \
    pip install --no-cache-dir -r deploy/requirements.txt
COPY servicios/ servicios/
COPY web/ web/
COPY manage.py ./
RUN groupadd --system aercom && useradd --system --gid aercom aercom \
    && chmod -R a+rX /app \
    && mkdir /app/staticfiles && chown aercom:aercom /app/staticfiles
USER aercom
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--no-control-socket", "servicios.wsgi"]
