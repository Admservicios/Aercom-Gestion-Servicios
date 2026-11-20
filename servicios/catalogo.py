from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ClienteForm, ContactoClienteForm, DocumentoClienteForm, EquipoForm, PlantaForm
from .models import Accion, Cliente, ContactoCliente, Cotizacion, DocumentoCliente, Equipo, PedidoServicio, Planta
from .permisos import edicion_catalogo_requerida, oficina_requerida


@oficina_requerida
def clientes(request, tipo=None):
    consulta = request.GET.get("q", "").strip()
    registros = Cliente.objects.all()
    if tipo:
        registros = registros.filter(tipo=tipo)
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
    acciones = Accion.objects.filter(ticket__cliente_ficha=registro).select_related(
        "ticket", "responsable",
    ).order_by(F("realizada_el").desc(nulls_first=True), "-asignada_el", "-pk")
    pendientes = acciones.filter(realizada_el__isnull=True).count()
    return render(request, "servicios/cliente.html", {
        "cliente": registro, "equipos": registro.equipos.select_related("planta"),
        "tickets": registro.tickets.order_by("-pk"),
        "cotizaciones": Cotizacion.objects.filter(ticket__cliente_ficha=registro),
        "pedidos": PedidoServicio.objects.filter(ticket__cliente_ficha=registro),
        "visitas": registro.visitas.select_related("planta").order_by("-fecha", "-hora_desde", "-pk"),
        "contactos": registro.contactos.select_related("planta"),
        "documentos": registro.documentos.all(),
        "pagina": Paginator(acciones, 30).get_page(request.GET.get("page")),
        "pendientes": pendientes,
    })


@edicion_catalogo_requerida
def contacto_cliente(request, cliente_id, pk=None):
    cliente = get_object_or_404(Cliente, pk=cliente_id)
    contacto = get_object_or_404(cliente.contactos, pk=pk) if pk else ContactoCliente(cliente=cliente)
    form = ContactoClienteForm(request.POST if request.method == "POST" else None, instance=contacto)
    if form.is_valid():
        form.save()
        return redirect("cliente", pk=cliente.pk)
    return render(request, "servicios/alta_ficha.html", {
        "form": form, "cliente_destino": cliente,
        "titulo": "Editar contacto" if pk else "Nuevo contacto",
    })


@edicion_catalogo_requerida
def documento_cliente(request, cliente_id):
    cliente = get_object_or_404(Cliente, pk=cliente_id)
    form = DocumentoClienteForm(
        request.POST if request.method == "POST" else None, instance=DocumentoCliente(cliente=cliente),
    )
    if form.is_valid():
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            if not cliente.documentos.filter(tipo=form.instance.tipo, referencia=form.instance.referencia).exists():
                raise
            form.add_error("referencia", "Ya existe un documento de ese tipo con esta referencia.")
        else:
            return redirect("cliente", pk=cliente.pk)
    return render(request, "servicios/alta_ficha.html", {
        "form": form, "cliente_destino": cliente, "titulo": "Registrar documento",
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
    historial = registro.registros_mantenimiento.select_related("registrado_por")
    return render(request, "servicios/equipo.html", {
        "equipo": registro, "tickets": registro.tickets.order_by("-pk"),
        "ultima_visita": historial.filter(visita_realizada=True).values_list("fecha", flat=True).first(),
        "pagina": Paginator(historial, 20).get_page(request.GET.get("page")),
    })


def alta(request, formulario, titulo, destino, initial=None):
    form = formulario(request.POST if request.method == "POST" else None, initial=initial)
    if form.is_bound and form.is_valid():
        return destino(form.save())
    return render(request, "servicios/alta_ficha.html", {"form": form, "titulo": titulo})


@edicion_catalogo_requerida
def nuevo_cliente(request):
    return alta(
        request, ClienteForm, "Nuevo cliente", lambda registro: redirect("cliente", pk=registro.pk),
        initial={"tipo": request.GET.get("tipo")},
    )


@edicion_catalogo_requerida
def nueva_planta(request):
    return alta(
        request, PlantaForm, "Nueva planta", lambda registro: redirect("planta", pk=registro.pk),
        initial={"cliente": request.GET.get("cliente")},
    )


@edicion_catalogo_requerida
def nuevo_equipo(request):
    return alta(
        request, EquipoForm, "Nuevo equipo", lambda registro: redirect("equipo", pk=registro.pk),
        initial={"cliente": request.GET.get("cliente")},
    )
