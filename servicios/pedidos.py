from django import forms
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Cliente, ContratoAbono, Cotizacion, PedidoServicio, Ticket
from .permisos import ROLES_REVISION_COTIZACION, Rol, oficina_requerida, requiere_roles, roles


Estado = PedidoServicio.Estado
Tipo = PedidoServicio.Tipo
crear_pedido_requerido = requiere_roles(ROLES_REVISION_COTIZACION)
seguimiento_requerido = requiere_roles(ROLES_REVISION_COTIZACION | {Rol.COORDINACION})


class PedidoForm(forms.ModelForm):
    cobertura_confirmada = forms.BooleanField(
        label="Confirmo que el trabajo está cubierto por el contrato seleccionado", required=False,
    )

    class Meta:
        model = PedidoServicio
        fields = ("referencia", "tipo", "contrato", "cotizaciones", "equipos", "alcance", "indicaciones", "modalidad_entrega")
        widgets = {"equipos": forms.CheckboxSelectMultiple, "cotizaciones": forms.CheckboxSelectMultiple}
        help_texts = {"indicaciones": "Incluí los repuestos, la prioridad o las condiciones para avanzar cuando correspondan."}

    def __init__(self, *args, cotizacion=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cotizacion = cotizacion
        ticket = self.instance.ticket
        cliente = ticket.cliente_ficha
        self.fields["equipos"].queryset = cliente.equipos.select_related("cliente")
        if cotizacion is not None:
            del self.fields["contrato"]
            del self.fields["cobertura_confirmada"]
            campo = self.fields["cotizaciones"]
            campo.queryset = Cotizacion.objects.filter(
                ticket__cliente_ficha=cliente, estado=Cotizacion.Estado.APROBADA,
            ).select_related("ticket")
            campo.label_from_instance = lambda item: f"C-{item.pk} · {item.referencia or item.ticket.asunto}"
            campo.required = True
        else:
            del self.fields["cotizaciones"]
            del self.fields["tipo"]
            del self.fields["modalidad_entrega"]
            hoy = timezone.localdate()
            campo = self.fields["contrato"]
            campo.queryset = cliente.contratos_abono.filter(vigente_desde__lte=hoy).filter(
                Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gte=hoy),
            )
            campo.label_from_instance = lambda item: f"{item.referencia} · desde {item.vigente_desde:%d/%m/%Y}"
            campo.required = True
            self.fields["cobertura_confirmada"].required = True

    def clean(self):
        datos = super().clean()
        if self.cotizacion and "cotizaciones" in datos and self.cotizacion not in datos["cotizaciones"]:
            self.add_error("cotizaciones", "Incluí la cotización desde la que se creó el pedido.")
        tipo = datos.get("tipo")
        modalidad = datos.get("modalidad_entrega")
        if tipo == Tipo.REPUESTOS and not modalidad:
            self.add_error("modalidad_entrega", "Indicá retiro en depósito o envío.")
        elif tipo == Tipo.SERVICIO and modalidad:
            self.add_error("modalidad_entrega", "La modalidad de entrega corresponde a una venta de repuestos.")
        return datos


class SeguimientoPedidoForm(forms.Form):
    estado = forms.ChoiceField(label="Registrar")
    fecha_agendada = forms.DateField(
        label="Fecha registrada en Excel", required=False, widget=forms.DateInput(attrs={"type": "date"}),
    )
    referencia = forms.CharField(label="Referencia o evidencia", required=False, max_length=180)
    nota = forms.CharField(label="Observaciones", required=False, max_length=2000, widget=forms.Textarea)

    def __init__(self, transiciones, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["estado"].choices = [("", "Elegí un paso"), *[(estado, estado.label) for estado in transiciones]]
        if Estado.AGENDADO not in transiciones:
            del self.fields["fecha_agendada"]

    def clean(self):
        datos = super().clean()
        if datos.get("estado") == Estado.AGENDADO and not datos.get("fecha_agendada"):
            self.add_error("fecha_agendada", "Indicá la fecha registrada en la Agenda General.")
        if datos.get("estado") == Estado.ENTREGADO and not datos.get("referencia"):
            self.add_error("referencia", "Indicá la confirmación o referencia informada por Logística.")
        return datos


def transiciones(usuario, pedido):
    asignados = roles(usuario)
    puede_crear = bool(asignados & ROLES_REVISION_COTIZACION)
    if pedido.estado == Estado.PREPARACION:
        return (Estado.ENVIADO,) if puede_crear else ()
    if pedido.tipo == Tipo.REPUESTOS:
        return (Estado.ENTREGADO,) if puede_crear and pedido.estado == Estado.ENVIADO else ()
    if puede_crear or Rol.COORDINACION in asignados:
        if pedido.estado == Estado.ENVIADO:
            return (Estado.PENDIENTE_AGENDAR, Estado.AGENDADO)
        if pedido.estado == Estado.PENDIENTE_AGENDAR:
            return (Estado.AGENDADO,)
    return ()


@oficina_requerida
def lista(request):
    consulta = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "")
    registros = PedidoServicio.objects.select_related("ticket__cliente_ficha")
    if consulta:
        filtro = Q(referencia__icontains=consulta) | Q(ticket__asunto__icontains=consulta) | Q(
            ticket__cliente_ficha__nombre__icontains=consulta,
        )
        numero = consulta.upper().removeprefix("PS-")
        if numero.isascii() and numero.isdecimal() and len(numero) <= 18:
            filtro |= Q(pk=int(numero))
        registros = registros.filter(filtro)
    if estado in Estado.values:
        registros = registros.filter(estado=estado)
    return render(request, "servicios/pedidos_lista.html", {
        "pagina": Paginator(registros, 30).get_page(request.GET.get("page")), "consulta": consulta,
        "estado": estado, "estados": Estado.choices,
    })


def mostrar_pedido(request, pedido, form=None, error=None):
    pasos = transiciones(request.user, pedido)
    return render(request, "servicios/pedido_detalle.html", {
        "pedido": pedido, "form": (form or SeguimientoPedidoForm(pasos)) if pasos else None, "error": error,
        "admite_visita": pedido.tipo == Tipo.SERVICIO and pedido.estado in (
            Estado.ENVIADO, Estado.PENDIENTE_AGENDAR, Estado.AGENDADO,
        ),
    })


@oficina_requerida
def detalle(request, pk):
    pedido = get_object_or_404(
        PedidoServicio.objects.select_related("ticket__cliente_ficha", "contrato")
        .prefetch_related("equipos", "cotizaciones", "cambios__autor"),
        pk=pk,
    )
    return mostrar_pedido(request, pedido)


@crear_pedido_requerido
@transaction.atomic
def nuevo(request, ticket_id=None, cotizacion_id=None):
    cotizacion = None
    if cotizacion_id is not None:
        cotizacion = get_object_or_404(Cotizacion, pk=cotizacion_id, estado=Cotizacion.Estado.APROBADA)
        ticket_id = cotizacion.ticket_id
    tickets = Ticket.objects.filter(cliente_ficha__isnull=False)
    if cotizacion is None:
        tickets = tickets.filter(cliente_ficha__tipo=Cliente.Tipo.ABONADO)
    if request.method == "POST":
        tickets = tickets.select_for_update(of=("self",))
    ticket = get_object_or_404(tickets, pk=ticket_id)
    inicial = {"equipos": [ticket.equipo_ficha_id]} if ticket.equipo_ficha_id else {}
    if cotizacion is not None:
        inicial.update(cotizaciones=[cotizacion.pk], alcance=cotizacion.alcance)
    pedido = PedidoServicio(ticket=ticket)
    form = PedidoForm(
        request.POST if request.method == "POST" else None, instance=pedido, initial=inicial, cotizacion=cotizacion,
    )
    if form.is_valid():
        form.save()
        pedido.cambios.create(autor=request.user, estado=pedido.estado)
        return redirect("pedido_servicio", pk=pedido.pk)
    return render(request, "servicios/pedido_form.html", {
        "pedido": pedido, "form": form, "cotizacion": cotizacion,
    })


@seguimiento_requerido
@require_POST
@transaction.atomic
def seguimiento(request, pk):
    pedido = get_object_or_404(PedidoServicio.objects.select_for_update(), pk=pk)
    pasos = transiciones(request.user, pedido)
    if not pasos:
        return mostrar_pedido(request, pedido, error="El pedido no admite ese cambio en su estado actual.")
    form = SeguimientoPedidoForm(pasos, request.POST)
    if form.is_valid():
        pedido.estado = form.cleaned_data["estado"]
        campos = ["estado"]
        if pedido.estado == Estado.AGENDADO:
            pedido.fecha_agendada = form.cleaned_data["fecha_agendada"]
            campos.append("fecha_agendada")
        pedido.save(update_fields=campos)
        pedido.cambios.create(
            autor=request.user, estado=pedido.estado, nota=form.cleaned_data["nota"],
            referencia=form.cleaned_data["referencia"],
        )
        return redirect("pedido_servicio", pk=pedido.pk)
    return mostrar_pedido(request, pedido, form=form)
