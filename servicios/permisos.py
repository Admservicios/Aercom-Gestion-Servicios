from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def es_oficina(usuario):
    return usuario.is_authenticated and usuario.groups.filter(name="Oficina").exists()


def oficina_requerida(vista):
    @login_required
    @wraps(vista)
    def protegida(request, *args, **kwargs):
        if not es_oficina(request.user):
            raise PermissionDenied
        return vista(request, *args, **kwargs)

    return protegida


def menu_por_rol(request):
    return {"es_oficina": es_oficina(request.user)}
