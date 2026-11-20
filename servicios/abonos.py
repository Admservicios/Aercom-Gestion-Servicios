from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ContratoAbonoForm
from .models import Cliente, ContratoAbono
from .permisos import edicion_catalogo_requerida, oficina_requerida


@oficina_requerida
def contrato(request, cliente_id, pk):
    registro = get_object_or_404(
        ContratoAbono.objects.select_related("cliente").prefetch_related("plantas", "equipos"),
        cliente_id=cliente_id, pk=pk,
    )
    return render(request, "servicios/contrato_abono.html", {"contrato": registro})


@edicion_catalogo_requerida
def guardar_contrato(request, cliente_id, pk=None):
    cliente = get_object_or_404(Cliente, pk=cliente_id, tipo=Cliente.Tipo.ABONADO)
    registro = get_object_or_404(cliente.contratos_abono, pk=pk) if pk else ContratoAbono(cliente=cliente)
    form = ContratoAbonoForm(request.POST if request.method == "POST" else None, instance=registro)
    if form.is_valid():
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            duplicado = cliente.contratos_abono.exclude(pk=pk).filter(
                referencia=registro.referencia, vigente_desde=registro.vigente_desde,
            )
            if not duplicado.exists():
                raise
            form.add_error("referencia", "Ya existe un contrato con esa referencia y fecha de inicio.")
        else:
            return redirect("contrato_abono", cliente_id=cliente.pk, pk=registro.pk)
    return render(request, "servicios/alta_ficha.html", {
        "form": form,
        "titulo": "Editar contrato de abono" if pk else "Nuevo contrato de abono",
        "cliente_destino": cliente,
        "texto_boton": "Guardar contrato",
    })
