from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Accion, CambioAccion, Ticket


class TicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ("asunto", "detalle", "origen", "cliente", "planta", "equipo")


class ResponsableField(forms.ModelChoiceField):
    def label_from_instance(self, persona):
        return persona.get_full_name() or persona.get_username()


class AccionForm(forms.ModelForm):
    responsable = ResponsableField(
        queryset=get_user_model().objects.filter(is_active=True).order_by("first_name")
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


def es_oficina(user):
    return user.groups.filter(name="Oficina").exists()


def verificar_oficina(user):
    if not es_oficina(user):
        raise PermissionDenied


def ver_campo(request, formulario=None, accion_id=None):
    acciones = Accion.objects.filter(responsable=request.user).select_related("ticket").order_by(
        F("realizada_el").asc(nulls_first=True), "-asignada_el",
    )
    return render(request, "servicios/campo.html", {
        "acciones": acciones, "estado_form": formulario or EstadoForm(auto_id=False), "accion_id": accion_id,
    })


@login_required
def inicio(request):
    if not es_oficina(request.user):
        return ver_campo(request)
    consulta = request.GET.get("q", "").strip()
    tickets = Ticket.objects.order_by("-pk")
    if consulta:
        filtro = Q(asunto__icontains=consulta) | Q(cliente__icontains=consulta) | Q(equipo__icontains=consulta)
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


@login_required
def nuevo(request):
    verificar_oficina(request.user)
    form = TicketForm(request.POST if request.method == "POST" else None)
    if form.is_bound and form.is_valid():
        registro = form.save(commit=False)
        registro.creado_por = request.user
        registro.save()
        return redirect("ticket", pk=registro.pk)
    return render(request, "servicios/nuevo.html", {"form": form})


def ver_ticket(request, registro, form, estado_form=None, accion_id=None):
    acciones = registro.acciones.select_related("responsable", "asignada_por", "realizada_por").prefetch_related(
        Prefetch("cambios", queryset=CambioAccion.objects.select_related("autor")),
    ).order_by("pk")
    return render(request, "servicios/ticket.html", {
        "ticket": registro, "acciones": acciones, "form": form,
        "estado_form": estado_form or EstadoForm(auto_id=False), "accion_id": accion_id,
    })


@login_required
def ticket(request, pk):
    verificar_oficina(request.user)
    return ver_ticket(request, get_object_or_404(Ticket, pk=pk), AccionForm())


@login_required
@require_POST
def agregar(request, pk):
    verificar_oficina(request.user)
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


@login_required
@require_POST
@transaction.atomic
def realizar(request, pk):
    propias = Accion.objects.filter(responsable=request.user)
    accion = get_object_or_404(propias, pk=pk)
    propias.filter(pk=pk, realizada_el__isnull=True).update(
        estado=Accion.Estado.REALIZADA, motivo_espera="",
        realizada_el=timezone.now(), realizada_por=request.user,
    )
    return volver_a_accion(request, accion)


@login_required
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
