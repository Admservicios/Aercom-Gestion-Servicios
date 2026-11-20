from django import forms
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Cliente, LlamadaServicioSAP, SolicitudFacturacionTrabajo, Ticket, Visita
from .permisos import ROLES_FACTURACION, Rol, requiere_roles


consulta_cierre_requerida = requiere_roles(ROLES_FACTURACION)
registro_cierre_requerido = requiere_roles({Rol.ADMINISTRACION})
Circuito = LlamadaServicioSAP.Circuito


class LlamadaForm(forms.ModelForm):
    class Meta:
        model = LlamadaServicioSAP
        fields = ("referencia", "circuito", "visita", "facturaciones", "observaciones")
        widgets = {"facturaciones": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ticket = self.instance.ticket
        visitas = self.fields["visita"]
        visitas.queryset = Visita.objects.filter(cliente_id=ticket.cliente_ficha_id).filter(
            Q(trabajos__ticket=ticket) | Q(pedidos__ticket=ticket) | Q(pedidos__cotizaciones__ticket=ticket),
        ).distinct()
        visitas.label_from_instance = lambda item: f"V-{item.pk} · {item.fecha:%d/%m/%Y}"
        facturaciones = self.fields["facturaciones"]
        facturaciones.queryset = ticket.solicitudes_facturacion.all()
        facturaciones.label_from_instance = lambda item: f"SF-{item.pk} · {item.get_modalidad_display()} · {item.get_estado_display()}"

    def clean_referencia(self):
        referencia = self.cleaned_data["referencia"].upper()
        if self.instance.cliente.llamadas_sap.filter(referencia=referencia).exists():
            raise forms.ValidationError("La llamada ya está registrada para este cliente. Buscala en Cierre administrativo.")
        return referencia

    def clean(self):
        datos = super().clean()
        facturaciones = datos.get("facturaciones")
        circuito = datos.get("circuito")
        if circuito == Circuito.PUNTUAL and facturaciones is not None:
            if not facturaciones:
                self.add_error("facturaciones", "Vinculá al menos una solicitud del trabajo que se factura por separado.")
            elif any(item.modalidad == SolicitudFacturacionTrabajo.Modalidad.ABONO for item in facturaciones):
                self.add_error("facturaciones", "Separá las solicitudes cubiertas por abono de las que se facturan aparte.")
        if circuito == Circuito.ABONO:
            if self.instance.cliente.tipo != Cliente.Tipo.ABONADO:
                self.add_error("circuito", "El circuito de abono solo corresponde a clientes abonados.")
            if facturaciones and any(item.modalidad != SolicitudFacturacionTrabajo.Modalidad.ABONO for item in facturaciones):
                self.add_error("facturaciones", "Vinculá solo solicitudes cubiertas por el abono.")
        return datos


class CierreForm(forms.Form):
    fecha = forms.DateField(label="Fecha del cierre en SAP", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    nota = forms.CharField(label="Observación del cierre", required=False, max_length=2000, widget=forms.Textarea)
    confirmado = forms.BooleanField(label="Confirmo que la llamada ya se cerró en SAP")

    def __init__(self, facturas, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.facturas = facturas

    def clean_fecha(self):
        fecha = self.cleaned_data["fecha"]
        if fecha > timezone.localdate():
            raise forms.ValidationError("La fecha de cierre no puede ser futura.")
        if any(item.fecha_factura > fecha for item in self.facturas):
            raise forms.ValidationError("El cierre no puede ser anterior a la emisión de la factura.")
        return fecha


@consulta_cierre_requerida
def lista(request):
    consulta = request.GET.get("q", "").strip()
    registros = LlamadaServicioSAP.objects.select_related("cliente", "ticket")
    if consulta:
        registros = registros.filter(
            Q(referencia__icontains=consulta) | Q(cliente__nombre__icontains=consulta) | Q(ticket__asunto__icontains=consulta),
        )
    return render(request, "servicios/cierres_lista.html", {
        "pagina": Paginator(registros, 30).get_page(request.GET.get("page")), "consulta": consulta,
    })


@consulta_cierre_requerida
def detalle(request, pk):
    llamada = get_object_or_404(
        LlamadaServicioSAP.objects.select_related("cliente", "ticket", "visita", "cierre_registrado_por")
        .prefetch_related("facturaciones__trabajos"),
        pk=pk,
    )
    return mostrar_llamada(request, llamada)


def mostrar_llamada(request, llamada, form=None, error=None):
    facturas = list(llamada.facturaciones.all())
    ids = {trabajo.pk for item in facturas for trabajo in item.trabajos.all()}
    trabajos = llamada.ticket.acciones.all()
    if llamada.visita_id:
        trabajos = trabajos.filter(visitas_agendadas=llamada.visita)
    elif ids:
        trabajos = trabajos.filter(pk__in=ids)
    facturacion_completa = bool(facturas) and all(item.factura_sap and item.fecha_factura for item in facturas)
    return render(request, "servicios/llamada_sap_detalle.html", {
        "llamada": llamada, "facturas": facturas, "trabajos": trabajos,
        "facturacion_completa": facturacion_completa, "error": error,
        "form": form or CierreForm(facturas, initial={"fecha": timezone.localdate()}),
    })


@registro_cierre_requerido
@transaction.atomic
def nueva(request, ticket_id=None, solicitud_id=None):
    inicial = {}
    if solicitud_id is not None:
        solicitud = get_object_or_404(SolicitudFacturacionTrabajo, pk=solicitud_id)
        ticket_id = solicitud.ticket_id
        circuito = Circuito.ABONO if solicitud.modalidad == SolicitudFacturacionTrabajo.Modalidad.ABONO else Circuito.PUNTUAL
        inicial = {"circuito": circuito, "facturaciones": [solicitud.pk]}
    tickets = Ticket.objects.filter(cliente_ficha__isnull=False)
    if request.method == "POST":
        tickets = tickets.select_for_update()
    ticket = get_object_or_404(tickets, pk=ticket_id)
    registro = LlamadaServicioSAP(cliente=ticket.cliente_ficha, ticket=ticket, registrada_por=request.user)
    form = LlamadaForm(request.POST if request.method == "POST" else None, instance=registro, initial=inicial)
    if form.is_valid():
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            if not registro.cliente.llamadas_sap.filter(referencia=registro.referencia).exists():
                raise
            form.add_error("referencia", "La llamada ya está registrada para este cliente. Buscala en Cierre administrativo.")
        else:
            return redirect("llamada_sap", pk=registro.pk)
    return render(request, "servicios/llamada_sap_form.html", {
        "ticket": ticket, "form": form,
        "referencias_campo": list(dict.fromkeys(
            referencia for referencia in ticket.acciones.values_list("resultados_visita__referencia_sap", flat=True)
            if referencia
        )),
    })


@registro_cierre_requerido
@transaction.atomic
def cerrar(request, pk):
    if request.method != "POST":
        return redirect("llamada_sap", pk=pk)
    llamada = get_object_or_404(LlamadaServicioSAP.objects.select_for_update(), pk=pk)
    if llamada.cerrada_en_sap:
        return redirect("llamada_sap", pk=pk)
    if llamada.circuito != Circuito.PUNTUAL:
        return mostrar_llamada(request, llamada, error="La regla de cierre de visitas de abono está pendiente de confirmar.")
    facturas = list(llamada.facturaciones.select_for_update(of=("self",)).order_by("pk"))
    if not facturas or any(not item.factura_sap or not item.fecha_factura for item in facturas):
        return mostrar_llamada(request, llamada, error="Registrá las facturas en SAP antes de asentar el cierre.")
    form = CierreForm(facturas, request.POST)
    if form.is_valid():
        llamada.cerrada_en_sap = form.cleaned_data["fecha"]
        llamada.observacion_cierre = form.cleaned_data["nota"]
        llamada.cierre_registrado_por = request.user
        llamada.cierre_registrado_el = timezone.now()
        llamada.respaldo_facturas = "\n".join(
            f"SF-{item.pk} · {item.factura_sap} · {item.fecha_factura:%d/%m/%Y}" for item in facturas
        )
        llamada.save(update_fields=[
            "cerrada_en_sap", "observacion_cierre", "cierre_registrado_por", "cierre_registrado_el", "respaldo_facturas",
        ])
        return redirect("llamada_sap", pk=pk)
    return mostrar_llamada(request, llamada, form=form)
