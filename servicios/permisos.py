from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


class Rol:
    RESPONSABLE = "Responsable del área"
    COMERCIAL = "Comercial"
    ADMINISTRACION = "Administración de Servicios"
    COORDINACION = "Coordinación"
    RESPONSABLE_TECNICO = "Responsable técnico"
    CAMPO = "Técnico de campo"
    OFICINA_ANTERIOR = "Oficina"


ROLES_OFICINA = {
    Rol.RESPONSABLE, Rol.COMERCIAL, Rol.ADMINISTRACION, Rol.COORDINACION,
    Rol.RESPONSABLE_TECNICO, Rol.OFICINA_ANTERIOR,
}
ROLES_SERVICIOS = ROLES_OFICINA | {Rol.CAMPO}
ROLES_EDICION_CATALOGO = {Rol.RESPONSABLE, Rol.ADMINISTRACION, Rol.OFICINA_ANTERIOR}


def roles(usuario):
    if not usuario.is_authenticated:
        return set()
    if not hasattr(usuario, "_roles_servicios"):
        usuario._roles_servicios = set(usuario.groups.values_list("name", flat=True))
    return usuario._roles_servicios


def es_oficina(usuario):
    return bool(roles(usuario) & ROLES_OFICINA)


def requiere_roles(permitidos):
    def decorar(vista):
        @login_required
        @wraps(vista)
        def protegida(request, *args, **kwargs):
            if not roles(request.user) & permitidos:
                raise PermissionDenied
            return vista(request, *args, **kwargs)

        return protegida

    return decorar


oficina_requerida = requiere_roles(ROLES_OFICINA)
campo_requerido = requiere_roles({Rol.CAMPO})
servicios_requeridos = requiere_roles(ROLES_SERVICIOS)
edicion_catalogo_requerida = requiere_roles(ROLES_EDICION_CATALOGO)


def menu_por_rol(request):
    asignados = roles(request.user)
    return {
        "es_oficina": bool(asignados & ROLES_OFICINA),
        "es_campo": Rol.CAMPO in asignados,
        "puede_editar_catalogo": bool(asignados & ROLES_EDICION_CATALOGO),
    }
