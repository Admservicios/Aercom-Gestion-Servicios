from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Accion, Ticket


class TicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ("asunto", "cliente", "equipo", "detalle")


class AccionForm(forms.ModelForm):
    responsable = forms.ModelChoiceField(
        queryset=get_user_model().objects.filter(is_active=True).order_by("first_name")
    )

    class Meta:
        model = Accion
        fields = ("titulo", "detalle", "responsable")
        labels = {"titulo": "Acción"}


def es_oficina(user):
    return user.groups.filter(name="Oficina").exists()


def verificar_oficina(user):
    if not es_oficina(user):
        raise PermissionDenied


@login_required
def inicio(request):
    if not es_oficina(request.user):
        acciones = Accion.objects.filter(responsable=request.user).select_related("ticket").order_by("realizada_el", "-asignada_el")
        return render(request, "servicios/campo.html", {"acciones": acciones})
    consulta = request.GET.get("q", "").strip()
    tickets = Ticket.objects.order_by("-pk")
    if consulta:
        filtro = Q(asunto__icontains=consulta) | Q(cliente__icontains=consulta) | Q(equipo__icontains=consulta)
        numero = consulta.upper().removeprefix("T-")
        if numero.isascii() and numero.isdecimal() and len(numero) <= 18:
            filtro |= Q(pk=int(numero))
        tickets = tickets.filter(filtro)
    return render(request, "servicios/inicio.html", {"tickets": tickets[:100], "consulta": consulta})


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


def ver_ticket(request, registro, form):
    acciones = registro.acciones.select_related("responsable", "realizada_por").order_by("pk")
    return render(request, "servicios/ticket.html", {"ticket": registro, "acciones": acciones, "form": form})


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
        accion.save()
        return redirect("ticket", pk=pk)
    return ver_ticket(request, registro, form)


@login_required
@require_POST
def realizar(request, pk):
    accion = get_object_or_404(Accion, pk=pk, responsable=request.user)
    Accion.objects.filter(pk=pk, responsable=request.user, realizada_el__isnull=True).update(
        realizada_el=timezone.now(), realizada_por=request.user,
    )
    if es_oficina(request.user):
        return redirect("ticket", pk=accion.ticket_id)
    return redirect("inicio")
