from django import forms
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Cliente, Cotizacion, SolicitudCotizacion, Ticket
from .permisos import ROLES_REVISION_COTIZACION, oficina_requerida, requiere_roles, roles


Estado = Cotizacion.Estado
gestion_cotizacion_requerida = requiere_roles(ROLES_REVISION_COTIZACION)


class CotizacionForm(forms.ModelForm):
    class Meta:
        model = Cotizacion
        fields = ("referencia", "alcance", "importe", "moneda")
        help_texts = {"importe": "Podés completar el importe y la moneda antes de registrar el envío."}

    def clean_moneda(self):
        return self.cleaned_data["moneda"].upper()


class RespuestaForm(forms.ModelForm):
    decision = forms.ChoiceField(choices=[
        (Estado.APROBADA, "Aprobada"), (Estado.RECHAZADA, "Rechazada"),
    ])
    nota = forms.CharField(label="Observaciones", required=False, max_length=2000, widget=forms.Textarea)

    class Meta:
        model = Cotizacion
        fields = ("confirmacion_correo", "orden_compra")
        help_texts = {"orden_compra": "Completá este campo cuando se haya recibido la OC."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.estado == Estado.APROBADA:
            del self.fields["decision"]

    def clean(self):
        datos = super().clean()
        if datos.get("decision", self.instance.estado) == Estado.APROBADA:
            if not (datos.get("confirmacion_correo") or datos.get("orden_compra")):
                self.add_error(None, "Registrá la confirmación por correo o la OC recibida según el requisito del cliente.")
        elif datos.get("decision") == Estado.RECHAZADA and not datos.get("nota"):
            self.add_error("nota", "Indicá la respuesta del cliente.")
        return datos


@oficina_requerida
def terceros(request):
    consulta = request.GET.get("q", "").strip()
    registros = Cotizacion.objects.filter(ticket__cliente_ficha__tipo=Cliente.Tipo.TERCERO).select_related(
        "ticket__cliente_ficha",
    )
    if consulta:
        filtro = Q(referencia__icontains=consulta) | Q(ticket__asunto__icontains=consulta) | Q(
            ticket__cliente_ficha__nombre__icontains=consulta,
        )
        numero = consulta.upper().removeprefix("C-")
        if numero.isascii() and numero.isdecimal() and len(numero) <= 18:
            filtro |= Q(pk=int(numero))
        registros = registros.filter(filtro)
    return render(request, "servicios/cotizaciones_terceros.html", {
        "pagina": Paginator(registros, 30).get_page(request.GET.get("page")), "consulta": consulta,
    })


@oficina_requerida
def detalle(request, pk):
    registro = get_object_or_404(
        Cotizacion.objects.select_related("ticket__cliente_ficha", "solicitud").prefetch_related("cambios__autor"),
        pk=pk,
    )
    return mostrar_cotizacion(request, registro)


def mostrar_cotizacion(request, registro, form=None, error=None):
    puede_gestionar = bool(roles(request.user) & ROLES_REVISION_COTIZACION)
    return render(request, "servicios/cotizacion_detalle.html", {
        "cotizacion": registro,
        "puede_ver_solicitud": registro.solicitud_id and (
            puede_gestionar or registro.solicitud.solicitante_id == request.user.pk
        ),
        "puede_editar": puede_gestionar and registro.estado == Estado.PREPARACION,
        "puede_responder": puede_gestionar and registro.estado in (Estado.ENVIADA, Estado.APROBADA),
        "form": form or RespuestaForm(instance=registro),
        "error": error,
    })


def guardar_formulario(request, registro, es_nueva=False):
    inicial = {"alcance": registro.solicitud.memoria} if es_nueva and registro.solicitud_id else {}
    form = CotizacionForm(request.POST if request.method == "POST" else None, instance=registro, initial=inicial)
    if form.is_valid():
        form.save()
        if es_nueva:
            registrar_cambio(registro, request.user)
        return redirect("cotizacion", pk=registro.pk)
    return render(request, "servicios/cotizacion_form.html", {
        "cotizacion": registro, "form": form, "es_nueva": es_nueva,
    })


@gestion_cotizacion_requerida
@transaction.atomic
def nueva(request, ticket_id=None, solicitud_id=None):
    solicitud = None
    if solicitud_id is not None:
        solicitud = get_object_or_404(SolicitudCotizacion, pk=solicitud_id, estado=SolicitudCotizacion.Estado.LISTA)
        ticket_id = solicitud.ticket_id
    tickets = Ticket.objects.filter(cliente_ficha__isnull=False)
    if request.method == "POST":
        tickets = tickets.select_for_update()
    ticket = get_object_or_404(tickets, pk=ticket_id)
    return guardar_formulario(request, Cotizacion(ticket=ticket, solicitud=solicitud), es_nueva=True)


@gestion_cotizacion_requerida
@transaction.atomic
def editar(request, pk):
    registros = Cotizacion.objects.filter(estado=Estado.PREPARACION)
    if request.method == "POST":
        registros = registros.select_for_update()
    registro = get_object_or_404(registros, pk=pk)
    return guardar_formulario(request, registro)


def registrar_cambio(cotizacion, autor, nota=""):
    cotizacion.cambios.create(autor=autor, estado=cotizacion.estado, nota=nota)


@gestion_cotizacion_requerida
@require_POST
@transaction.atomic
def registrar_envio(request, pk):
    registro = get_object_or_404(Cotizacion.objects.select_for_update(), pk=pk, estado=Estado.PREPARACION)
    if registro.importe is None or not registro.moneda:
        return mostrar_cotizacion(request, registro, error="Completá el importe y la moneda antes de registrar el envío.")
    registro.estado = Estado.ENVIADA
    registro.save(update_fields=["estado"])
    registrar_cambio(registro, request.user)
    return redirect("cotizacion", pk=pk)


@gestion_cotizacion_requerida
@require_POST
@transaction.atomic
def registrar_respuesta(request, pk):
    registro = get_object_or_404(
        Cotizacion.objects.select_for_update(), pk=pk, estado__in=(Estado.ENVIADA, Estado.APROBADA),
    )
    form = RespuestaForm(request.POST, instance=registro)
    if form.is_valid():
        decision = form.cleaned_data.get("decision", registro.estado)
        nota = form.cleaned_data["nota"]
        if form.changed_data or nota:
            registro.estado = decision
            registro.save(update_fields=["estado", "confirmacion_correo", "orden_compra"])
            evidencias = [
                etiqueta + valor for etiqueta, valor in (
                    ("Correo: ", registro.confirmacion_correo), ("OC recibida: ", registro.orden_compra),
                ) if valor
            ]
            registrar_cambio(registro, request.user, "\n".join(filter(None, [nota, *evidencias])))
        return redirect("cotizacion", pk=pk)
    return mostrar_cotizacion(request, registro, form=form)
