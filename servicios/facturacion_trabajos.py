from django import forms
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from .models import Accion, Cliente, Cotizacion, PedidoServicio, SolicitudFacturacionTrabajo, Ticket
from .permisos import ROLES_FACTURACION, oficina_requerida, requiere_roles, roles


Estado = SolicitudFacturacionTrabajo.Estado
Modalidad = SolicitudFacturacionTrabajo.Modalidad
ESTADOS_ABIERTOS = (Estado.SOLICITADA, Estado.EN_ESPERA)
gestion_requerida = requiere_roles(ROLES_FACTURACION)
datos_comprobante = (
    "referencia_presupuesto", "orden_compra", "correo_envio", "centro_costo", "moneda", "referencia_cambio",
    "tipo_comprobante", "hes", "portal", "documentacion_faltante", "observaciones",
)


class DatosFacturacionForm(forms.ModelForm):
    def clean_moneda(self):
        return self.cleaned_data["moneda"].upper()


class SolicitudFacturacionForm(DatosFacturacionForm):
    class Meta:
        model = SolicitudFacturacionTrabajo
        fields = ("modalidad", "trabajos", "cotizacion", *datos_comprobante, "cobranza_aplica")
        widgets = {"trabajos": forms.CheckboxSelectMultiple}
        help_texts = {"trabajos": "Seleccioná los trabajos incluidos en esta solicitud cuando estén registrados en el ticket."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        registro = self.instance
        relacionadas = Q(ticket=registro.ticket)
        trabajos = Q(ticket=registro.ticket)
        if registro.pedido_id:
            relacionadas |= Q(pedidos_servicio=registro.pedido)
            trabajos |= Q(ticket_id__in=registro.pedido.cotizaciones.values("ticket_id"))
        campo_trabajos = self.fields["trabajos"]
        campo_trabajos.queryset = Accion.objects.filter(trabajos).order_by("pk")
        campo_trabajos.label_from_instance = lambda item: f"T-{item.ticket_id} · {item.titulo}"
        campo = self.fields["cotizacion"]
        campo.queryset = Cotizacion.objects.filter(relacionadas, estado=Cotizacion.Estado.APROBADA).distinct()
        campo.label_from_instance = lambda item: f"C-{item.pk} · {item.referencia or item.alcance[:60]}"
        if registro.pedido_id and registro.pedido.contrato_id:
            self.fields["modalidad"].choices = [(Modalidad.ABONO, Modalidad.ABONO.label)]
            campo.queryset = Cotizacion.objects.none()
        elif registro.ticket.cliente_ficha.tipo != Cliente.Tipo.ABONADO or (
            registro.pedido_id and registro.pedido.tipo == PedidoServicio.Tipo.REPUESTOS
        ):
            self.fields["modalidad"].choices = [
                opcion for opcion in self.fields["modalidad"].choices if opcion[0] != Modalidad.ABONO
            ]


    def clean(self):
        datos = super().clean()
        trabajos = datos.get("trabajos")
        if datos.get("modalidad") in (Modalidad.PREVIA, Modalidad.POSTERIOR) and trabajos:
            if any(trabajo.facturacion == Accion.Facturacion.ABONO for trabajo in trabajos):
                self.add_error("trabajos", "Separá los trabajos cubiertos por el abono de los que se facturan aparte.")
        return datos


class RegistroFacturacionForm(DatosFacturacionForm):
    class Meta:
        model = SolicitudFacturacionTrabajo
        fields = (*datos_comprobante, "factura_sap", "fecha_factura", "cobranza_aplica", "referencia_cobro", "fecha_cobro")
        widgets = {
            campo: forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})
            for campo in ("fecha_factura", "fecha_cobro")
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.modalidad == Modalidad.ABONO:
            for campo in ("factura_sap", "fecha_factura", "cobranza_aplica", "referencia_cobro", "fecha_cobro"):
                del self.fields[campo]
        else:
            if self.instance.factura_sap:
                self.fields["factura_sap"].required = True
                self.fields["fecha_factura"].required = True
            if self.instance.fecha_cobro:
                for campo in ("cobranza_aplica", "referencia_cobro", "fecha_cobro"):
                    self.fields[campo].required = True


    def clean_fecha_factura(self):
        fecha = self.cleaned_data["fecha_factura"]
        if fecha and self.instance.llamadas_sap.filter(cerrada_en_sap__lt=fecha).exists():
            raise forms.ValidationError("La fecha de emisión no puede quedar después de un cierre SAP ya registrado.")
        return fecha


def solicitudes_facturacion_visibles(usuario):
    registros = SolicitudFacturacionTrabajo.objects.all()
    return registros if roles(usuario) & ROLES_FACTURACION else registros.filter(solicitante=usuario)


@oficina_requerida
def lista(request):
    consulta = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "")
    registros = solicitudes_facturacion_visibles(request.user).select_related("ticket__cliente_ficha", "solicitante")
    if consulta:
        registros = registros.filter(
            Q(ticket__cliente_ficha__nombre__icontains=consulta) | Q(ticket__asunto__icontains=consulta)
            | Q(orden_compra__icontains=consulta) | Q(factura_sap__icontains=consulta),
        )
    if estado == "abiertas":
        registros = registros.filter(estado__in=ESTADOS_ABIERTOS)
    elif estado in Estado.values:
        registros = registros.filter(estado=estado)
    return render(request, "servicios/facturacion_trabajos_lista.html", {
        "pagina": Paginator(registros, 30).get_page(request.GET.get("page")), "consulta": consulta,
        "estado": estado, "estados": [("abiertas", "Abiertas"), *Estado.choices],
    })


@oficina_requerida
def detalle(request, pk):
    registro = get_object_or_404(
        solicitudes_facturacion_visibles(request.user).select_related(
            "ticket__cliente_ficha", "pedido", "cotizacion", "solicitante",
        ).prefetch_related("movimientos__autor", "trabajos"),
        pk=pk,
    )
    return render(request, "servicios/facturacion_trabajo_detalle.html", {"solicitud": registro})


@oficina_requerida
@transaction.atomic
def nueva(request, ticket_id=None, pedido_id=None):
    pedido = None
    inicial = {}
    if pedido_id is not None:
        pedido = get_object_or_404(PedidoServicio, pk=pedido_id)
        ticket_id = pedido.ticket_id
        if pedido.contrato_id:
            inicial["modalidad"] = Modalidad.ABONO
        else:
            cotizaciones = list(pedido.cotizaciones.filter(estado=Cotizacion.Estado.APROBADA)[:2])
            if len(cotizaciones) == 1:
                cotizacion = cotizaciones[0]
                inicial.update(
                    cotizacion=cotizacion.pk, referencia_presupuesto=cotizacion.referencia,
                    orden_compra=cotizacion.orden_compra, moneda=cotizacion.moneda,
                )
    tickets = Ticket.objects.filter(cliente_ficha__isnull=False)
    if request.method == "POST":
        tickets = tickets.select_for_update()
    ticket = get_object_or_404(tickets, pk=ticket_id)
    registro = SolicitudFacturacionTrabajo(ticket=ticket, pedido=pedido, solicitante=request.user)
    form = SolicitudFacturacionForm(
        request.POST if request.method == "POST" else None, instance=registro, initial=inicial,
    )
    if form.is_valid():
        registro.actualizar_estado()
        form.save()
        registro.movimientos.create(autor=request.user, estado=registro.estado)
        return redirect("facturacion_trabajo", pk=registro.pk)
    return render(request, "servicios/facturacion_trabajo_form.html", {
        "form": form, "solicitud": registro, "titulo": "Solicitar facturación de trabajo",
    })


@gestion_requerida
@transaction.atomic
def gestionar(request, pk):
    registros = SolicitudFacturacionTrabajo.objects.select_for_update() if request.method == "POST" else SolicitudFacturacionTrabajo.objects
    registro = get_object_or_404(registros, pk=pk)
    version = registro.movimientos.values_list("pk", flat=True).first()
    form = RegistroFacturacionForm(request.POST if request.method == "POST" else None, instance=registro)
    if request.method == "POST" and request.POST.get("version") != str(version):
        return render(request, "servicios/facturacion_trabajo_form.html", {
            "form": RegistroFacturacionForm(instance=registro), "solicitud": registro,
            "titulo": "Actualizar facturación del trabajo", "version": version,
            "conflicto": "Otra persona actualizó la solicitud. Revisá los datos actuales antes de guardar.",
        }, status=409)
    if form.is_valid():
        if form.has_changed():
            registro.actualizar_estado()
            form.save()
            notas = []
            for campo, etiqueta in (
                ("documentacion_faltante", "Documentación pendiente"),
                ("factura_sap", "Factura SAP"),
                ("referencia_cobro", "Cobro"),
            ):
                if campo in form.changed_data:
                    notas.append(f"{etiqueta}: {getattr(registro, campo) or 'sin registrar'}")
            registro.movimientos.create(autor=request.user, estado=registro.estado, nota="\n".join(notas))
        return redirect("facturacion_trabajo", pk=pk)
    return render(request, "servicios/facturacion_trabajo_form.html", {
        "form": form, "solicitud": registro, "titulo": "Actualizar facturación del trabajo", "version": version,
    })
