from django import forms
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Cotizacion, RepuestoSolicitud, RespuestaPrecio, SolicitudPrecio
from .permisos import ROLES_REVISION_COTIZACION, requiere_roles


precios_requeridos = requiere_roles(ROLES_REVISION_COTIZACION)


class SolicitudPrecioForm(forms.ModelForm):
    class Meta:
        model = SolicitudPrecio
        fields = ("codigo", "descripcion", "destinatario", "solicitada_el")
        widgets = {"solicitada_el": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}
        help_texts = {"solicitada_el": "Indicá cuándo hiciste el pedido de precio."}


class RespuestaPrecioForm(forms.ModelForm):
    class Meta:
        model = RespuestaPrecio
        fields = ("recibida_el", "fuente", "precio", "moneda", "vigente_hasta", "respuesta")
        widgets = {
            campo: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
            for campo in ("recibida_el", "vigente_hasta")
        }

    def clean_moneda(self):
        return self.cleaned_data["moneda"].upper()


@precios_requeridos
def lista(request):
    consulta = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "")
    registros = SolicitudPrecio.objects.annotate(
        respondida=Exists(RespuestaPrecio.objects.filter(solicitud_id=OuterRef("pk"))),
    )
    if consulta:
        registros = registros.filter(Q(codigo__icontains=consulta) | Q(descripcion__icontains=consulta))
    if estado in {"pendiente", "respondida"}:
        registros = registros.filter(respondida=estado == "respondida")
    return render(request, "servicios/precios_lista.html", {
        "pagina": Paginator(registros, 30).get_page(request.GET.get("page")),
        "consulta": consulta, "estado": estado,
    })


@precios_requeridos
def detalle(request, pk):
    registro = get_object_or_404(
        SolicitudPrecio.objects.select_related("solicitante", "repuesto", "anterior"),
        pk=pk,
    )
    return render(request, "servicios/precio_detalle.html", {
        "solicitud": registro,
        "respuestas": registro.respuestas.select_related("registrado_por"),
        "actualizaciones": registro.actualizaciones.all(),
        "hoy": timezone.localdate(),
    })


@precios_requeridos
def nueva(request, cotizacion_id=None, repuesto_id=None, anterior_id=None):
    registro = SolicitudPrecio(solicitante=request.user)
    inicial = {"destinatario": "Compras", "solicitada_el": timezone.localdate()}
    if anterior_id is not None:
        anterior = get_object_or_404(SolicitudPrecio, pk=anterior_id)
        registro.anterior = anterior
        registro.repuesto_id = anterior.repuesto_id
        registro.cotizacion_id = anterior.cotizacion_id
        inicial.update(codigo=anterior.codigo, descripcion=anterior.descripcion, destinatario=anterior.destinatario)
    elif repuesto_id is not None:
        registro.repuesto = get_object_or_404(RepuestoSolicitud, pk=repuesto_id)
        inicial.update(codigo=registro.repuesto.referencia, descripcion=registro.repuesto.descripcion)
    elif cotizacion_id is not None:
        registro.cotizacion = get_object_or_404(Cotizacion, pk=cotizacion_id)

    form = SolicitudPrecioForm(request.POST if request.method == "POST" else None, instance=registro, initial=inicial)
    if form.is_valid():
        return redirect("solicitud_precio", pk=form.save().pk)
    return render(request, "servicios/precio_form.html", {
        "form": form, "solicitud": registro, "es_respuesta": False,
        "busqueda": form["codigo"].value() or form["descripcion"].value(),
    })


@precios_requeridos
@transaction.atomic
def responder(request, pk):
    registros = SolicitudPrecio.objects.select_for_update() if request.method == "POST" else SolicitudPrecio.objects
    solicitud = get_object_or_404(registros, pk=pk)
    form = RespuestaPrecioForm(
        request.POST if request.method == "POST" else None,
        instance=RespuestaPrecio(solicitud=solicitud, registrado_por=request.user),
        initial={"recibida_el": timezone.localdate()},
    )
    if form.is_valid():
        solicitud.respuestas.get_or_create(**form.cleaned_data, defaults={"registrado_por": request.user})
        return redirect("solicitud_precio", pk=solicitud.pk)
    return render(request, "servicios/precio_form.html", {
        "form": form, "solicitud": solicitud, "es_respuesta": True,
    })
