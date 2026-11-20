from django import forms
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .campo_servicios import visitas_de_campo
from .facturacion_trabajos import solicitudes_facturacion_visibles
from .forms import TicketForm, VinculoTicketForm
from .models import Accion, CambioAccion, PedidoServicio, Ticket
from .permisos import ROLES_SERVICIOS, Rol, es_oficina, oficina_requerida, roles, servicios_requeridos
from .solicitudes import solicitudes_visibles


class ResponsableField(forms.ModelChoiceField):
    def label_from_instance(self, persona):
        return persona.get_full_name() or persona.get_username()


class AccionForm(forms.ModelForm):
    responsable = ResponsableField(
        queryset=get_user_model().objects.filter(
            is_active=True, groups__name__in=ROLES_SERVICIOS,
        ).order_by("first_name", "username").distinct()
    )

    class Meta:
        model = Accion
        fields = ("titulo", "tipo", "detalle", "responsable", "facturacion")
        labels = {"titulo": "Acción", "facturacion": "Facturación"}


class EstadoForm(forms.Form):
    estado = forms.ChoiceField(choices=[
        (Accion.Estado.EN_CURSO, Accion.Estado.EN_CURSO.label),
        (Accion.Estado.EN_ESPERA, Accion.Estado.EN_ESPERA.label),
    ])
    motivo = forms.CharField(label="Qué falta para avanzar", required=False, max_length=240)

    def clean(self):
        datos = super().clean()
        if datos.get("estado") == Accion.Estado.EN_ESPERA and not datos.get("motivo"):
            self.add_error("motivo", "Indicá qué falta para avanzar.")
        return datos


def ver_campo(request, formulario=None, accion_id=None):
    acciones = Accion.objects.filter(responsable=request.user).select_related(
        "ticket__cliente_ficha", "ticket__equipo_ficha",
    ).prefetch_related(
        Prefetch("visitas_agendadas", queryset=visitas_de_campo(request.user), to_attr="mis_visitas"),
    ).order_by(
        F("realizada_el").asc(nulls_first=True), "-asignada_el",
    )
    return render(request, "servicios/campo.html", {
        "acciones": acciones, "estado_form": formulario or EstadoForm(auto_id=False), "accion_id": accion_id,
    })


@servicios_requeridos
def inicio(request):
    if not es_oficina(request.user):
        return ver_campo(request)
    if "q" in request.GET or "responsable" in request.GET:
        return redirect(f"{reverse('tickets')}?{request.GET.urlencode()}")
    return render(request, "servicios/menu_oficina.html")


@oficina_requerida
def tickets(request):
    consulta = request.GET.get("q", "").strip()
    tickets = Ticket.objects.select_related("cliente_ficha").order_by("-pk")
    if consulta:
        filtro = (
            Q(asunto__icontains=consulta) | Q(cliente__icontains=consulta) | Q(equipo__icontains=consulta)
            | Q(cliente_ficha__nombre__icontains=consulta) | Q(cliente_ficha__codigo__icontains=consulta)
            | Q(equipo_ficha__nombre__icontains=consulta) | Q(equipo_ficha__codigo__icontains=consulta)
        )
        numero = consulta.upper().removeprefix("T-")
        if numero.isascii() and numero.isdecimal() and len(numero) <= 18:
            filtro |= Q(pk=int(numero))
        tickets = tickets.filter(filtro)
    responsable = ResponsableField(
        queryset=get_user_model().objects.filter(is_active=True).order_by("first_name"),
        required=False, label="Pendientes por responsable",
    )
    filtro_form = forms.Form(request.GET)
    filtro_form.fields["responsable"] = responsable
    if filtro_form.is_valid() and (persona := filtro_form.cleaned_data["responsable"]):
        tickets = tickets.filter(acciones__responsable=persona, acciones__realizada_el__isnull=True).distinct()
    return render(request, "servicios/inicio.html", {
        "tickets": tickets[:100], "consulta": consulta, "filtro_form": filtro_form,
    })


@oficina_requerida
def nuevo(request):
    form = TicketForm(
        request.POST if request.method == "POST" else None,
        initial={campo: request.GET.get(campo) for campo in VinculoTicketForm.Meta.fields},
    )
    if form.is_bound and form.is_valid():
        registro = form.save(commit=False)
        registro.creado_por = request.user
        registro.save()
        return redirect("ticket", pk=registro.pk)
    return render(request, "servicios/nuevo.html", {"form": form})


@oficina_requerida
@transaction.atomic
def vincular_ticket(request, pk):
    registros = Ticket.objects.select_for_update() if request.method == "POST" else Ticket.objects
    registro = get_object_or_404(registros, pk=pk)
    cliente_anterior = registro.cliente_ficha_id
    planta_anterior = registro.planta_ficha_id
    form = VinculoTicketForm(request.POST if request.method == "POST" else None, instance=registro)
    if form.is_bound and form.is_valid():
        if (registro.cliente_ficha_id, registro.planta_ficha_id) != (cliente_anterior, planta_anterior) and (
            registro.acciones.filter(visitas_agendadas__isnull=False).exists()
            or registro.pedidos_servicio.filter(visitas__isnull=False).exists()
        ):
            form.add_error("planta_ficha", "El ticket está vinculado a una visita. Conservá su cliente y planta.")
        elif registro.cliente_ficha_id != cliente_anterior and (
            registro.solicitudes_cotizacion.exists() or registro.cotizaciones.exists()
            or registro.pedidos_servicio.exists() or registro.solicitudes_facturacion.exists()
            or registro.llamadas_sap.exists()
        ):
            form.add_error("cliente_ficha", "El ticket tiene registros asociados. Conservá su cliente.")
        else:
            form.instance.save(update_fields=VinculoTicketForm.Meta.fields)
            return redirect("ticket", pk=pk)
    return render(request, "servicios/vincular_ticket.html", {"ticket": registro, "form": form})


def ver_ticket(request, registro, form, estado_form=None, accion_id=None):
    acciones = registro.acciones.select_related("responsable", "asignada_por", "realizada_por").prefetch_related(
        Prefetch("cambios", queryset=CambioAccion.objects.select_related("autor")),
        "resultados_visita__visita",
    ).order_by("pk")
    return render(request, "servicios/ticket.html", {
        "ticket": registro, "acciones": acciones, "form": form,
        "solicitudes_cotizacion": solicitudes_visibles(request.user).filter(ticket=registro),
        "cotizaciones": registro.cotizaciones.all(),
        "solicitudes_facturacion": solicitudes_facturacion_visibles(request.user).filter(ticket=registro),
        "pedidos": PedidoServicio.objects.filter(Q(ticket=registro) | Q(cotizaciones__ticket=registro)).distinct(),
        "estado_form": estado_form or EstadoForm(auto_id=False), "accion_id": accion_id,
    })


@oficina_requerida
def ticket(request, pk):
    return ver_ticket(request, get_object_or_404(Ticket, pk=pk), AccionForm())


@oficina_requerida
@require_POST
def agregar(request, pk):
    registro = get_object_or_404(Ticket, pk=pk)
    form = AccionForm(request.POST)
    if form.is_valid():
        accion = form.save(commit=False)
        accion.ticket = registro
        accion.asignada_por = request.user
        accion.save()
        return redirect("ticket", pk=pk)
    return ver_ticket(request, registro, form)


def volver_a_accion(request, accion):
    if es_oficina(request.user):
        return redirect("ticket", pk=accion.ticket_id)
    return redirect("inicio")


@servicios_requeridos
@require_POST
@transaction.atomic
def realizar(request, pk):
    propias = Accion.objects.filter(responsable=request.user)
    accion = get_object_or_404(propias.select_for_update(), pk=pk)
    if not accion.realizada_el and Rol.CAMPO in roles(request.user):
        if accion.visitas_agendadas.filter(tecnicos=request.user).exists():
            return redirect("servicios_tecnicos")
    propias.filter(pk=pk, realizada_el__isnull=True).update(
        estado=Accion.Estado.REALIZADA, motivo_espera="",
        realizada_el=timezone.now(), realizada_por=request.user,
    )
    return volver_a_accion(request, accion)


@servicios_requeridos
@require_POST
@transaction.atomic
def cambiar_estado(request, pk):
    propias = Accion.objects.filter(responsable=request.user)
    accion = get_object_or_404(propias, pk=pk)
    form = EstadoForm(request.POST, auto_id=False)
    if not form.is_valid():
        if es_oficina(request.user):
            return ver_ticket(request, accion.ticket, AccionForm(), form, accion.pk)
        return ver_campo(request, form, accion.pk)
    estado = form.cleaned_data["estado"]
    motivo = form.cleaned_data["motivo"] if estado == Accion.Estado.EN_ESPERA else ""
    if propias.filter(pk=pk, realizada_el__isnull=True).exclude(estado=estado, motivo_espera=motivo).update(
        estado=estado, motivo_espera=motivo,
    ):
        CambioAccion.objects.create(accion=accion, autor=request.user, estado=estado, motivo=motivo)
    return volver_a_accion(request, accion)
