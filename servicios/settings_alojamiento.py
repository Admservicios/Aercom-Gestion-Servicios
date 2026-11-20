import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403

host = os.environ["AERCOM_HOST"]
if not host or any(caracter in host for caracter in " /:*"):
    raise ImproperlyConfigured("AERCOM_HOST debe ser un nombre de host sin esquema, ruta ni puerto.")

if not os.environ.get("POSTGRES_HOST"):
    raise ImproperlyConfigured("El alojamiento requiere PostgreSQL.")

ALLOWED_HOSTS = [host]
CSRF_TRUSTED_ORIGINS = [f"https://{host}"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 3600
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
STATIC_ROOT = Path("/app/staticfiles")

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
