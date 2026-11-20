from django import forms
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import Accion, Ticket
from .permisos import ROLES_SERVICIOS, es_oficina, oficina_requerida, servicios_requeridos


class ResponsableField(forms.ModelChoiceField):
    def label_from_instance(self, persona):
        return persona.get_full_name() or persona.get_username()


def responsables_disponibles():
    return get_user_model().objects.filter(
        is_active=True, groups__name__in=ROLES_SERVICIOS,
    ).order_by("first_name", "username").distinct()


class FiltroPendientesForm(forms.Form):
    q = forms.CharField(label="Buscar por acción, ticket, cliente o equipo", required=False)
    responsable = ResponsableField(queryset=responsables_disponibles(), required=False)
    estado = forms.ChoiceField(
        choices=[("", "Todos"), *[(estado, estado.label) for estado in Accion.Estado if estado != Accion.Estado.REALIZADA]],
        required=False,
    )


class ProximoPasoForm(forms.ModelForm):
    class Meta:
        model = Accion
        fields = ("proximo_paso",)


class DocumentosTicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ("documentos",)
        widgets = {"documentos": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        campo = self.fields["documentos"]
        campo.queryset = self.instance.cliente_ficha.documentos.all()
        campo.label_from_instance = lambda item: f"{item.tipo} · {item.referencia}"


def acciones_pendientes():
    return Accion.objects.filter(realizada_el__isnull=True)


@oficina_requerida
def pendientes(request):
    form = FiltroPendientesForm(request.GET)
    acciones = Accion.objects.none()
    if form.is_valid():
        acciones = acciones_pendientes().select_related(
            "responsable", "depende_de", "ticket__cliente_ficha", "ticket__equipo_ficha",
        ).order_by("-asignada_el", "-pk")
        datos = form.cleaned_data
        if datos["q"]:
            consulta = datos["q"]
            filtro = (
                Q(titulo__icontains=consulta) | Q(ticket__asunto__icontains=consulta)
                | Q(ticket__cliente_ficha__nombre__icontains=consulta) | Q(ticket__cliente_ficha__codigo__icontains=consulta)
                | Q(ticket__equipo_ficha__nombre__icontains=consulta) | Q(ticket__equipo_ficha__codigo__icontains=consulta)
                | Q(ticket__cliente__icontains=consulta) | Q(ticket__equipo__icontains=consulta)
            )
            numero = consulta.upper().removeprefix("T-")
            if numero.isascii() and numero.isdecimal() and len(numero) <= 18:
                filtro |= Q(ticket_id=int(numero))
            acciones = acciones.filter(filtro)
        if datos["responsable"]:
            acciones = acciones.filter(responsable=datos["responsable"])
        if datos["estado"]:
            acciones = acciones.filter(estado=datos["estado"])
    filtros = request.GET.copy()
    filtros.pop("page", None)
    return render(request, "servicios/pendientes.html", {
        "form": form, "pagina": Paginator(acciones, 30).get_page(request.GET.get("page")),
        "filtros_pagina": filtros.urlencode(),
    })


@servicios_requeridos
@transaction.atomic
def proximo_paso(request, pk):
    registros = Accion.objects.filter(responsable=request.user, realizada_el__isnull=True)
    if request.method == "POST":
        registros = registros.select_for_update()
    accion = get_object_or_404(registros, pk=pk)
    form = ProximoPasoForm(request.POST if request.method == "POST" else None, instance=accion)
    destino = f"{reverse('ticket', args=[accion.ticket_id])}#accion-{accion.pk}" if es_oficina(request.user) else reverse("inicio")
    if form.is_valid():
        if form.has_changed():
            accion.save(update_fields=["proximo_paso"])
            accion.cambios.create(autor=request.user, estado=accion.estado, proximo_paso=accion.proximo_paso)
        return redirect(destino)
    return render(request, "servicios/proximo_paso_accion.html", {"accion": accion, "form": form, "destino": destino})


@oficina_requerida
@transaction.atomic
def documentos_ticket(request, pk):
    registros = Ticket.objects.filter(cliente_ficha__isnull=False)
    if request.method == "POST":
        registros = registros.select_for_update()
    ticket = get_object_or_404(registros, pk=pk)
    form = DocumentosTicketForm(request.POST if request.method == "POST" else None, instance=ticket)
    if form.is_valid():
        form.save()
        return redirect("ticket", pk=pk)
    return render(request, "servicios/documentos_ticket.html", {"ticket": ticket, "form": form})


def respuesta_accion_bloqueada():
    return HttpResponse("Completá primero la acción previa de este trabajo.", status=409)
