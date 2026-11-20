from datetime import timedelta

from django import forms
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .models import Accion, CategoriaEspera, MovimientoTiempoAccion
from .permisos import Rol, oficina_requerida, roles
from .seguimiento import ResponsableField, responsables_disponibles


Tipo = MovimientoTiempoAccion.Tipo
puestos = (
    Rol.RESPONSABLE, Rol.ADMINISTRACION, Rol.COMERCIAL, Rol.COORDINACION,
    Rol.RESPONSABLE_TECNICO, Rol.CAMPO, Rol.OFICINA_ANTERIOR,
)


def registrar_movimiento(accion, tipo, autor, *, motivo="", categoria="", fecha=None):
    responsable = accion.responsable
    asignados = roles(responsable)
    ultimo = accion.movimientos_tiempo.last()
    # Si cambian los grupos de un usuario, la pasada mantiene el puesto que tenía al recibirla.
    if ultimo and tipo != Tipo.DERIVACION:
        puesto = ultimo.puesto
    else:
        puesto = next((rol for rol in puestos if rol in asignados), "Sin puesto registrado")
    return accion.movimientos_tiempo.create(
        tipo=tipo, autor=autor, responsable=responsable, puesto=puesto, motivo=motivo,
        categoria_espera=categoria, ocurrio_el=fecha or timezone.now(),
    )


def resumir_tiempos(movimientos, hasta):
    pasadas = []
    totales = {}
    for indice, movimiento in enumerate(movimientos):
        tipo = movimiento.tipo
        if not pasadas or tipo == Tipo.DERIVACION:
            if pasadas:
                pasadas[-1]["fin"] = movimiento.ocurrio_el
            pasadas.append({
                "puesto": movimiento.puesto, "responsable": movimiento.responsable,
                "inicio": movimiento.ocurrio_el, "fin": None, "total": timedelta(), "esperas": {},
            })
        pasada = pasadas[-1]
        if tipo == Tipo.FINALIZACION:
            pasada["fin"] = movimiento.ocurrio_el
            continue
        proximo = movimientos[indice + 1].ocurrio_el if indice + 1 < len(movimientos) else hasta
        duracion = max(timedelta(), proximo - movimiento.ocurrio_el)
        pasada["total"] += duracion
        if tipo == Tipo.ESPERA:
            etiqueta = movimiento.get_categoria_espera_display() or CategoriaEspera.OTRA.label
            pasada["esperas"][etiqueta] = pasada["esperas"].get(etiqueta, timedelta()) + duracion

    for pasada in pasadas:
        total = totales.setdefault(pasada["puesto"], {"total": timedelta(), "esperas": {}})
        total["total"] += pasada["total"]
        for categoria, demora in pasada["esperas"].items():
            total["esperas"][categoria] = total["esperas"].get(categoria, timedelta()) + demora
    return pasadas, totales


class DerivarForm(forms.Form):
    responsable = ResponsableField(queryset=responsables_disponibles(), label="Nuevo responsable")
    motivo = forms.CharField(label="Motivo de la derivación", max_length=240)

    def __init__(self, accion, *args, **kwargs):
        super().__init__(*args, **kwargs)
        campo = self.fields["responsable"]
        campo.queryset = campo.queryset.exclude(pk=accion.responsable_id)


@oficina_requerida
def lista(request):
    consulta = request.GET.get("q", "").strip()
    resultado = Accion.objects.filter(
        Exists(MovimientoTiempoAccion.objects.filter(accion_id=OuterRef("pk"))),
    ).select_related("ticket", "responsable").order_by("-pk")
    if consulta:
        filtro = Q(titulo__icontains=consulta) | Q(ticket__asunto__icontains=consulta)
        numero = consulta.upper().removeprefix("T-")
        if numero.isascii() and numero.isdecimal() and len(numero) <= 18:
            filtro |= Q(ticket_id=int(numero))
        resultado = resultado.filter(filtro)
    return render(request, "servicios/tiempos_lista.html", {
        "pagina": Paginator(resultado, 30).get_page(request.GET.get("page")), "consulta": consulta,
    })


@oficina_requerida
def detalle(request, pk):
    accion = get_object_or_404(Accion.objects.select_related("ticket"), pk=pk)
    movimientos = list(accion.movimientos_tiempo.select_related("responsable", "autor"))
    pasadas, totales = resumir_tiempos(movimientos, timezone.now())
    return render(request, "servicios/tiempos_accion.html", {
        "accion": accion, "movimientos": movimientos, "pasadas": pasadas, "totales": totales,
        "registro_parcial": bool(movimientos) and movimientos[0].tipo != Tipo.ASIGNACION,
    })


@oficina_requerida
@transaction.atomic
def derivar(request, pk):
    registros = Accion.objects.filter(realizada_el__isnull=True)
    if request.method == "POST":
        registros = registros.select_for_update()
    accion = get_object_or_404(registros, pk=pk)
    form = DerivarForm(accion, request.POST if request.method == "POST" else None)
    if form.is_valid():
        accion.responsable = form.cleaned_data["responsable"]
        accion.asignada_por = request.user
        accion.asignada_el = timezone.now()
        accion.estado = Accion.Estado.ASIGNADA
        accion.motivo_espera = ""
        accion.categoria_espera = ""
        accion.save(update_fields=[
            "responsable", "asignada_por", "asignada_el", "estado", "motivo_espera", "categoria_espera",
        ])
        registrar_movimiento(
            accion, Tipo.DERIVACION, request.user, motivo=form.cleaned_data["motivo"], fecha=accion.asignada_el,
        )
        return redirect(f"{reverse('ticket', args=[accion.ticket_id])}#accion-{accion.pk}")
    return render(request, "servicios/derivar_accion.html", {"accion": accion, "form": form})
