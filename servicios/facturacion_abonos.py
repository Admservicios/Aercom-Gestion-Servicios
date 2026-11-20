from calendar import monthrange
from datetime import date

from django import forms
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Exists, OuterRef, Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Cliente, ContratoAbono, FacturacionMensualAbono
from .permisos import ROLES_FACTURACION_ABONOS, requiere_roles


facturacion_abonos_requerida = requiere_roles(ROLES_FACTURACION_ABONOS)
Estado = FacturacionMensualAbono.Estado


class FiltroPeriodoForm(forms.Form):
    periodo = forms.DateField(
        label="Período", input_formats=["%Y-%m"],
        widget=forms.DateInput(format="%Y-%m", attrs={"type": "month"}),
    )
    q = forms.CharField(label="Buscar cliente por nombre o código", required=False)


class FacturacionMensualForm(forms.ModelForm):
    class Meta:
        model = FacturacionMensualAbono
        fields = (
            "estado", "fecha_prevista", "modalidad", "importe", "moneda", "ajuste", "requiere_oc",
            "orden_compra", "requiere_hes", "hes", "portal", "observaciones", "factura_sap", "fecha_factura",
        )
        widgets = {
            campo: forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})
            for campo in ("fecha_prevista", "fecha_factura")
        }
        help_texts = {
            "importe": "Confirmá el importe del período con el ajuste aplicable.",
            "ajuste": "Anotá el porcentaje, importe o criterio aplicado según el contrato.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.estado == Estado.FACTURADA:
            self.fields["estado"].choices = [(Estado.FACTURADA, Estado.FACTURADA.label)]

    def clean_moneda(self):
        return self.cleaned_data["moneda"].upper()


def contratos_del_mes(periodo):
    ultimo = periodo.replace(day=monthrange(periodo.year, periodo.month)[1])
    return ContratoAbono.objects.filter(vigente_desde__lte=ultimo).filter(
        Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gte=periodo),
    )


@facturacion_abonos_requerida
def lista(request):
    datos = request.GET.copy()
    if "periodo" not in datos:
        datos["periodo"] = timezone.localdate().strftime("%Y-%m")
    form = FiltroPeriodoForm(datos)
    clientes = Cliente.objects.none()
    mes = form["periodo"].value()
    if form.is_valid():
        periodo = form.cleaned_data["periodo"]
        mes = periodo.strftime("%Y-%m")
        clientes = Cliente.objects.filter(tipo=Cliente.Tipo.ABONADO).annotate(
            tiene_contrato=Exists(contratos_del_mes(periodo).filter(cliente_id=OuterRef("pk"))),
        ).prefetch_related(Prefetch(
            "facturacion_mensual", queryset=FacturacionMensualAbono.objects.filter(periodo=periodo),
            to_attr="control_del_mes",
        ))
        consulta = form.cleaned_data["q"]
        if consulta:
            clientes = clientes.filter(Q(nombre__icontains=consulta) | Q(codigo__icontains=consulta))
    return render(request, "servicios/facturacion_abonos.html", {
        "form": form, "pagina": Paginator(clientes, 30).get_page(request.GET.get("page")),
        "periodo": mes, "consulta": form["q"].value(),
    })


def datos_del_contrato(contrato):
    return {
        "importe": contrato.valor,
        "moneda": contrato.moneda,
        "requiere_oc": contrato.requiere_oc,
        "requiere_hes": contrato.requiere_hes,
        "portal": contrato.portal,
        "observaciones": contrato.requisitos_administrativos,
    }


@facturacion_abonos_requerida
@transaction.atomic
def gestionar(request, cliente_id, mes):
    try:
        periodo = date.fromisoformat(f"{mes}-01")
    except ValueError as error:
        raise Http404 from error
    clientes = Cliente.objects.filter(tipo=Cliente.Tipo.ABONADO)
    if request.method == "POST":
        clientes = clientes.select_for_update()
    cliente = get_object_or_404(clientes, pk=cliente_id)
    # Serializa la carga y la edición del mismo cliente en el período.
    registro = cliente.facturacion_mensual.filter(periodo=periodo).first()
    es_nuevo = registro is None
    if es_nuevo:
        registro = FacturacionMensualAbono(cliente=cliente, periodo=periodo, actualizado_por=request.user)
    contratos = contratos_del_mes(periodo).filter(cliente=cliente)
    contrato = registro.contrato
    puede_elegir_contrato = contrato is None
    if puede_elegir_contrato:
        contrato_id = request.GET.get("contrato", "")
        if contrato_id.isascii() and contrato_id.isdecimal() and len(contrato_id) <= 18:
            contrato = get_object_or_404(contratos, pk=int(contrato_id))
        elif es_nuevo and contratos.count() == 1:
            contrato = contratos.first()
        registro.contrato = contrato
    inicial = datos_del_contrato(contrato) if es_nuevo and contrato else {}
    if es_nuevo and not contratos.exists():
        inicial["estado"] = Estado.NO_CORRESPONDE
    version = "" if es_nuevo else registro.actualizado_el.isoformat()
    if request.method == "POST" and request.POST.get("version", "") != version:
        return render(request, "servicios/facturacion_abono_conflicto.html", {
            "cliente": cliente, "mes": mes,
        }, status=409)
    form = FacturacionMensualForm(
        request.POST if request.method == "POST" else None, instance=registro, initial=inicial,
    )
    if form.is_valid():
        registro.actualizado_por = request.user
        form.save()
        return redirect("facturacion_abono_mes", cliente_id=cliente.pk, mes=mes)
    return render(request, "servicios/facturacion_abono_mes.html", {
        "cliente": cliente, "registro": registro, "mes": mes, "form": form, "contrato": contrato,
        "opciones_contrato": contratos if puede_elegir_contrato else (),
        "es_nuevo": es_nuevo, "version": version,
    })
