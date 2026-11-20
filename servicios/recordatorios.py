from django import forms
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import AvisoOperativo, Cliente, RecepcionAviso, Recordatorio, Ticket, Visita
from .permisos import Rol, es_oficina, oficina_requerida, servicios_requeridos
from .seguimiento import ResponsableField, responsables_disponibles


ROLES_AVISO_CAMPO = {Rol.RESPONSABLE, Rol.COORDINACION, Rol.RESPONSABLE_TECNICO, Rol.OFICINA_ANTERIOR}


class DestinatariosField(forms.ModelMultipleChoiceField):
    label_from_instance = ResponsableField.label_from_instance


class DestinatariosForm(forms.Form):
    destinatarios = DestinatariosField(
        queryset=responsables_disponibles(), widget=forms.CheckboxSelectMultiple, required=False,
    )


class RecordatorioForm(forms.ModelForm):
    responsable = ResponsableField(queryset=responsables_disponibles())
    destinatarios = DestinatariosField(
        queryset=responsables_disponibles(), widget=forms.CheckboxSelectMultiple, required=False,
        label="Personas adicionales a avisar",
    )

    class Meta:
        model = Recordatorio
        fields = ("titulo", "detalle", "tipo", "disparador", "fecha", "accion", "responsable", "destinatarios")
        labels = {"accion": "Acción vinculada"}
        help_texts = {"accion": "Si esta fecha marca un vencimiento o una demora, vinculá la acción para mostrarla en Gerencia."}
        widgets = {"fecha": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.ticket_id:
            campo = self.fields["accion"]
            campo.queryset = self.instance.ticket.acciones.order_by("pk")
            campo.label_from_instance = lambda accion: accion.titulo
        else:
            del self.fields["accion"]

    def clean(self):
        datos = super().clean()
        if datos.get("disparador") == Recordatorio.Disparador.FECHA and not datos.get("fecha"):
            self.add_error("fecha", "Indicá la fecha en que debe aparecer el aviso.")
        if datos.get("disparador") == Recordatorio.Disparador.PROXIMA_VISITA:
            if not self.instance.ticket_id:
                self.add_error("disparador", "Creá este recordatorio desde un ticket con cliente vinculado.")
            if datos.get("fecha"):
                self.add_error("fecha", "Dejá la fecha vacía para usar la de la próxima visita.")
        return datos


def guardar_destinatarios(aviso, ids):
    aviso.recepciones.exclude(destinatario_id__in=ids).update(activo=False)
    existentes = set(aviso.recepciones.values_list("destinatario_id", flat=True))
    aviso.recepciones.filter(destinatario_id__in=ids, activo=False).update(activo=True)
    RecepcionAviso.objects.bulk_create([
        RecepcionAviso(aviso=aviso, destinatario_id=pk) for pk in ids - existentes
    ])


def avisar_novedad_campo(alerta):
    aviso = AvisoOperativo.objects.create(alerta_campo=alerta)
    destinatarios = responsables_disponibles().filter(groups__name__in=ROLES_AVISO_CAMPO)
    guardar_destinatarios(aviso, set(destinatarios.values_list("pk", flat=True)))


def asociar_proximas_visitas(cliente_id):
    # Serializa altas de visitas y recordatorios del mismo cliente.
    Cliente.objects.select_for_update(no_key=True).get(pk=cliente_id)
    registros = Recordatorio.objects.filter(
        disparador=Recordatorio.Disparador.PROXIMA_VISITA, visita__isnull=True,
        ticket__cliente_ficha_id=cliente_id,
    ).select_related("ticket")
    for registro in registros:
        inicio = timezone.localtime(registro.creado_el)
        visitas = Visita.objects.filter(cliente_id=cliente_id).filter(
            Q(fecha__gt=inicio.date()) | Q(fecha=inicio.date(), hora_hasta__gt=inicio.time()),
        )
        if registro.ticket.planta_ficha_id:
            visitas = visitas.filter(planta_id=registro.ticket.planta_ficha_id)
        visita = visitas.first()
        if visita:
            registro.visita = visita
            registro.save(update_fields=["visita"])


def avisos_disponibles():
    hoy = timezone.localdate()
    return Q(alerta_campo__isnull=False) | Q(atendido_el__isnull=False) | Q(
        recordatorio__fecha__lte=hoy,
    ) | Q(recordatorio__visita__fecha__lte=hoy)


@oficina_requerida
def lista(request):
    registros = Recordatorio.objects.select_related("ticket", "visita", "responsable", "aviso")
    return render(request, "servicios/recordatorios.html", {
        "pagina": Paginator(registros, 30).get_page(request.GET.get("page")), "hoy": timezone.localdate(),
    })


@oficina_requerida
@transaction.atomic
def nuevo(request, ticket_id=None):
    ticket = None
    if ticket_id is not None:
        tickets = Ticket.objects.filter(cliente_ficha__isnull=False)
        if request.method == "POST":
            tickets = tickets.select_for_update()
        ticket = get_object_or_404(tickets, pk=ticket_id)
    registro = Recordatorio(ticket=ticket, creado_por=request.user)
    form = RecordatorioForm(request.POST if request.method == "POST" else None, instance=registro)
    if form.is_valid():
        form.save()
        aviso = AvisoOperativo.objects.create(recordatorio=registro)
        guardar_destinatarios(aviso, {registro.responsable_id, *(item.pk for item in form.cleaned_data["destinatarios"])})
        if registro.disparador == Recordatorio.Disparador.PROXIMA_VISITA:
            asociar_proximas_visitas(ticket.cliente_ficha_id)
        return redirect("aviso_operativo", pk=aviso.pk)
    return render(request, "servicios/recordatorio_form.html", {"form": form, "ticket": ticket})


@servicios_requeridos
def avisos(request):
    registros = RecepcionAviso.objects.filter(destinatario=request.user, activo=True).filter(
        aviso_id__in=AvisoOperativo.objects.filter(avisos_disponibles()),
    ).select_related("aviso__recordatorio__visita", "aviso__alerta_campo").order_by("-aviso_id")
    return render(request, "servicios/avisos_operativos.html", {
        "pagina": Paginator(registros, 30).get_page(request.GET.get("page")),
    })


@servicios_requeridos
def detalle(request, pk):
    registros = AvisoOperativo.objects.select_related(
        "recordatorio__visita", "recordatorio__ticket", "recordatorio__responsable", "alerta_campo__autor", "atendido_por",
    )
    if not es_oficina(request.user):
        registros = registros.filter(avisos_disponibles(), recepciones__destinatario=request.user, recepciones__activo=True)
    aviso = get_object_or_404(registros, pk=pk)
    recepciones = list(aviso.recepciones.select_related("destinatario").order_by("destinatario__username"))
    propia = next((item for item in recepciones if item.destinatario_id == request.user.pk and item.activo), None)
    disponible = aviso.alerta_campo_id or aviso.atendido_el or (
        aviso.recordatorio.fecha_activacion and aviso.recordatorio.fecha_activacion <= timezone.localdate()
    )
    return render(request, "servicios/aviso_detalle.html", {
        "aviso": aviso, "recepciones": recepciones if es_oficina(request.user) else (),
        "propia": propia, "disponible": disponible,
    })


@oficina_requerida
@transaction.atomic
def destinatarios(request, pk):
    registros = AvisoOperativo.objects.select_for_update() if request.method == "POST" else AvisoOperativo.objects
    aviso = get_object_or_404(registros, pk=pk)
    seleccionados = list(aviso.recepciones.filter(activo=True).values_list("destinatario_id", flat=True))
    form = DestinatariosForm(
        request.POST if request.method == "POST" else None, initial={"destinatarios": seleccionados},
    )
    if form.is_valid():
        ids = {item.pk for item in form.cleaned_data["destinatarios"]}
        if aviso.recordatorio_id:
            ids.add(aviso.recordatorio.responsable_id)
        if aviso.atendido_por_id and not aviso.resuelto_el:
            ids.add(aviso.atendido_por_id)
        guardar_destinatarios(aviso, ids)
        return redirect("aviso_operativo", pk=pk)
    return render(request, "servicios/aviso_destinatarios.html", {"aviso": aviso, "form": form})


@servicios_requeridos
@require_POST
@transaction.atomic
def gestionar(request, pk):
    aviso = get_object_or_404(AvisoOperativo.objects.select_for_update(of=("self",)).filter(avisos_disponibles()), pk=pk)
    propia = get_object_or_404(aviso.recepciones, destinatario=request.user, activo=True)
    operacion = request.POST.get("operacion")
    ahora = timezone.now()
    if operacion == "visto":
        if not propia.visto_el:
            propia.visto_el = ahora
            propia.save(update_fields=["visto_el"])
    elif operacion == "tomar" and not aviso.atendido_por_id and not aviso.resuelto_el:
        aviso.atendido_por = request.user
        aviso.atendido_el = ahora
        aviso.save(update_fields=["atendido_por", "atendido_el"])
        if not propia.visto_el:
            propia.visto_el = ahora
            propia.save(update_fields=["visto_el"])
    elif operacion == "resolver" and aviso.atendido_por_id == request.user.pk and not aviso.resuelto_el:
        aviso.resuelto_el = ahora
        aviso.save(update_fields=["resuelto_el"])
    return redirect("aviso_operativo", pk=pk)
