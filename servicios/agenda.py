from django import forms
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Accion, Cliente, PedidoServicio, Ticket, Visita
from .permisos import ROLES_EDICION_AGENDA, Rol, oficina_requerida, requiere_roles


edicion_agenda_requerida = requiere_roles(ROLES_EDICION_AGENDA)
estados_agendables = (
    PedidoServicio.Estado.ENVIADO, PedidoServicio.Estado.PENDIENTE_AGENDAR, PedidoServicio.Estado.AGENDADO,
)
campos_horario = ("fecha", "hora_desde", "hora_hasta", "referencia_excel")
widgets_horario = {
    "fecha": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    "hora_desde": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
    "hora_hasta": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
}


def tecnicos_activos():
    return get_user_model().objects.filter(is_active=True, groups__name=Rol.CAMPO).order_by("first_name", "username")


class TecnicoField(forms.ModelChoiceField):
    def label_from_instance(self, persona):
        return persona.get_full_name() or persona.username


class TecnicosField(forms.ModelMultipleChoiceField):
    label_from_instance = TecnicoField.label_from_instance


class FiltroAgendaForm(forms.Form):
    dia = forms.DateField(widget=widgets_horario["fecha"], input_formats=["%Y-%m-%d"], label="Día")
    tecnico = TecnicoField(queryset=tecnicos_activos(), required=False, label="Técnico")


class VisitaForm(forms.ModelForm):
    tecnicos = TecnicosField(queryset=tecnicos_activos(), widget=forms.CheckboxSelectMultiple, label="Técnicos")

    class Meta:
        model = Visita
        fields = ("planta", *campos_horario, "tecnicos", "pedidos", "trabajos", "indicaciones")
        widgets = {**widgets_horario, "pedidos": forms.CheckboxSelectMultiple, "trabajos": forms.CheckboxSelectMultiple}

    def __init__(self, *args, pedido=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.pedido = pedido
        cliente = self.instance.cliente
        self.fields["planta"].queryset = cliente.plantas.select_related("cliente")
        campo = self.fields["pedidos"]
        campo.queryset = PedidoServicio.objects.filter(
            ticket__cliente_ficha=cliente, tipo=PedidoServicio.Tipo.SERVICIO, estado__in=estados_agendables,
        ).select_related("ticket")
        campo.label_from_instance = lambda item: f"PS-{item.pk} · {item.referencia or item.ticket.asunto}"
        campo = self.fields["trabajos"]
        campo.queryset = Accion.objects.filter(ticket__cliente_ficha=cliente, realizada_el__isnull=True).order_by("-pk")
        campo.label_from_instance = lambda item: f"T-{item.ticket_id} · {item.titulo}"

    def clean(self):
        datos = super().clean()
        if "trabajos" in datos and "pedidos" in datos:
            if not (datos["pedidos"] or datos["trabajos"]):
                self.add_error("trabajos", "Vinculá al menos un pedido de servicio o un trabajo pendiente.")
            if self.pedido and self.pedido not in datos["pedidos"]:
                self.add_error("pedidos", "Incluí el pedido desde el que iniciás la programación.")
        return datos


class ReprogramarForm(forms.ModelForm):
    motivo = forms.CharField(label="Motivo de la reprogramación", max_length=300)

    class Meta:
        model = Visita
        fields = campos_horario
        widgets = widgets_horario

    def clean(self):
        datos = super().clean()
        if not any(campo in self.changed_data for campo in ("fecha", "hora_desde", "hora_hasta")):
            self.add_error(None, "Indicá una fecha u horario diferente.")
        return datos


def registrar_movimiento(visita, autor, motivo=""):
    visita.movimientos.create(autor=autor, motivo=motivo, **{
        campo: getattr(visita, campo) for campo in campos_horario
    })


def actualizar_pedidos(pedidos, usuario):
    for pedido in pedidos:
        fecha = pedido.visitas.values_list("fecha", flat=True).first()
        if pedido.estado != PedidoServicio.Estado.AGENDADO or pedido.fecha_agendada != fecha:
            pedido.estado = PedidoServicio.Estado.AGENDADO
            pedido.fecha_agendada = fecha
            pedido.save(update_fields=["estado", "fecha_agendada"])
            pedido.cambios.create(
                autor=usuario, estado=pedido.estado, referencia=f"Agenda operativa · {fecha:%d/%m/%Y}",
            )


@oficina_requerida
def lista(request):
    hoy = timezone.localdate()
    datos = request.GET.copy()
    if "dia" not in datos:
        datos["dia"] = hoy.isoformat()
    form = FiltroAgendaForm(datos)
    visitas = Visita.objects.none()
    if form.is_valid():
        visitas = Visita.objects.filter(fecha=form.cleaned_data["dia"]).select_related("cliente", "planta").prefetch_related(
            "tecnicos", "trabajos", "pedidos__ticket",
        )
        if form.cleaned_data["tecnico"]:
            visitas = visitas.filter(tecnicos=form.cleaned_data["tecnico"])
    return render(request, "servicios/agenda.html", {"form": form, "visitas": visitas})


@oficina_requerida
def detalle(request, pk):
    visita = get_object_or_404(
        Visita.objects.select_related("cliente", "planta").prefetch_related(
            "tecnicos", "trabajos__ticket", "pedidos__ticket", "movimientos__autor",
        ),
        pk=pk,
    )
    return render(request, "servicios/visita_detalle.html", {"visita": visita})


@edicion_agenda_requerida
@transaction.atomic
def nueva(request, cliente_id=None, pedido_id=None):
    pedido = None
    inicial = {"fecha": timezone.localdate()}
    if pedido_id is not None:
        pedido = get_object_or_404(
            PedidoServicio.objects.select_related("ticket"), pk=pedido_id,
            tipo=PedidoServicio.Tipo.SERVICIO, estado__in=estados_agendables,
        )
        cliente_id = pedido.ticket.cliente_ficha_id
        inicial.update(pedidos=[pedido.pk], planta=pedido.ticket.planta_ficha_id)
        if pedido.fecha_agendada:
            inicial["fecha"] = pedido.fecha_agendada
    cliente = get_object_or_404(Cliente, pk=cliente_id)
    visita = Visita(cliente=cliente)
    form = VisitaForm(
        request.POST if request.method == "POST" else None, instance=visita, initial=inicial, pedido=pedido,
    )
    if form.is_valid():
        pedidos = list(PedidoServicio.objects.select_for_update().filter(
            pk__in=form.cleaned_data["pedidos"], estado__in=estados_agendables,
        ).order_by("pk"))
        trabajos = form.cleaned_data["trabajos"]
        tickets = Ticket.objects.select_for_update().filter(pk__in=trabajos.values("ticket_id")).order_by("pk")
        planta = form.cleaned_data["planta"]
        if any(ticket.cliente_ficha_id != cliente.pk for ticket in tickets):
            form.add_error("trabajos", "Uno de los trabajos cambió de cliente. Revisá la selección.")
        elif planta and (
            any(ticket.planta_ficha_id not in (None, planta.pk) for ticket in tickets)
            or any(item.ticket.planta_ficha_id not in (None, planta.pk) for item in pedidos)
        ):
            form.add_error("planta", "La planta debe coincidir con la de los trabajos y pedidos que tengan planta informada.")
        if not form.errors:
            form.save()
            registrar_movimiento(visita, request.user)
            actualizar_pedidos(pedidos, request.user)
            return redirect("visita", pk=visita.pk)
    return render(request, "servicios/visita_form.html", {
        "form": form, "cliente": cliente, "titulo": "Registrar visita de Excel", "texto_boton": "Guardar visita",
    })


@edicion_agenda_requerida
@transaction.atomic
def reprogramar(request, pk):
    registros = Visita.objects.select_for_update() if request.method == "POST" else Visita.objects
    visita = get_object_or_404(registros, pk=pk)
    if visita.resultados.exists():
        return HttpResponse("La visita ya tiene resultados. Registrá una nueva visita para los trabajos pendientes.", status=409)
    form = ReprogramarForm(request.POST if request.method == "POST" else None, instance=visita)
    if form.is_valid():
        pedidos = list(PedidoServicio.objects.select_for_update().filter(visitas=visita).order_by("pk"))
        visita.save(update_fields=campos_horario)
        registrar_movimiento(visita, request.user, form.cleaned_data["motivo"])
        actualizar_pedidos(pedidos, request.user)
        return redirect("visita", pk=pk)
    return render(request, "servicios/visita_form.html", {
        "form": form, "cliente": visita.cliente, "visita": visita,
        "titulo": "Registrar reprogramación de Excel", "texto_boton": "Guardar reprogramación",
    })
