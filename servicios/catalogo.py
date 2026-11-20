from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ClienteForm, EquipoForm, PlantaForm
from .models import Cliente, Equipo, Planta
from .permisos import oficina_requerida


@oficina_requerida
def clientes(request, tipo):
    if tipo not in Cliente.Tipo.values:
        raise Http404
    consulta = request.GET.get("q", "").strip()
    registros = Cliente.objects.filter(tipo=tipo)
    if consulta:
        registros = registros.filter(
            Q(nombre__icontains=consulta) | Q(codigo__icontains=consulta) | Q(referencia_sap__icontains=consulta),
        )
    return render(request, "servicios/clientes.html", {
        "tipo": tipo, "consulta": consulta, "pagina": Paginator(registros, 50).get_page(request.GET.get("page")),
    })


@oficina_requerida
def cliente(request, pk):
    registro = get_object_or_404(Cliente, pk=pk)
    return render(request, "servicios/cliente.html", {
        "cliente": registro, "equipos": registro.equipos.select_related("planta"),
        "tickets": registro.tickets.order_by("-pk"),
    })


@oficina_requerida
def planta(request, pk):
    registro = get_object_or_404(Planta.objects.select_related("cliente"), pk=pk)
    return render(request, "servicios/planta.html", {
        "planta": registro, "equipos": registro.equipos.all(),
        "tickets": registro.tickets.order_by("-pk"),
    })


@oficina_requerida
def equipos(request):
    consulta = request.GET.get("q", "").strip()
    registros = Equipo.objects.select_related("cliente", "planta")
    if consulta:
        registros = registros.filter(
            Q(nombre__icontains=consulta) | Q(codigo__icontains=consulta) | Q(numero_serie__icontains=consulta)
            | Q(cliente__nombre__icontains=consulta) | Q(planta__nombre__icontains=consulta),
        )
    return render(request, "servicios/equipos.html", {
        "consulta": consulta, "pagina": Paginator(registros, 50).get_page(request.GET.get("page")),
    })


@oficina_requerida
def equipo(request, pk):
    registro = get_object_or_404(Equipo.objects.select_related("cliente", "planta"), pk=pk)
    return render(request, "servicios/equipo.html", {
        "equipo": registro, "tickets": registro.tickets.order_by("-pk"),
    })


def alta(request, formulario, titulo, destino, initial=None):
    form = formulario(request.POST if request.method == "POST" else None, initial=initial)
    if form.is_bound and form.is_valid():
        return destino(form.save())
    return render(request, "servicios/alta_ficha.html", {"form": form, "titulo": titulo})


@oficina_requerida
def nuevo_cliente(request):
    return alta(
        request, ClienteForm, "Nuevo cliente", lambda registro: redirect("cliente", pk=registro.pk),
        initial={"tipo": request.GET.get("tipo")},
    )


@oficina_requerida
def nueva_planta(request):
    return alta(
        request, PlantaForm, "Nueva planta", lambda registro: redirect("planta", pk=registro.pk),
        initial={"cliente": request.GET.get("cliente")},
    )


@oficina_requerida
def nuevo_equipo(request):
    return alta(
        request, EquipoForm, "Nuevo equipo", lambda registro: redirect("equipo", pk=registro.pk),
        initial={"cliente": request.GET.get("cliente")},
    )
