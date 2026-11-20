from django import forms
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from .models import Accion, ResultadoTrabajoVisita, Visita
from .permisos import Rol, campo_requerido, es_oficina, roles, servicios_requeridos


Estado = ResultadoTrabajoVisita.Estado


class ResultadoForm(forms.ModelForm):
    class Meta:
        model = ResultadoTrabajoVisita
        fields = ("estado", "observacion", "referencia_sap")
        help_texts = {"observacion": "Si quedó parcial o pendiente, indicá qué se hizo y qué falta."}

    def clean(self):
        datos = super().clean()
        if datos.get("estado") in (Estado.PARCIAL, Estado.PENDIENTE) and not datos.get("observacion"):
            self.add_error("observacion", "Indicá qué falta para poder continuar el trabajo.")
        return datos


def visitas_de_campo(usuario):
    return Visita.objects.filter(tecnicos=usuario)


@servicios_requeridos
def lista(request):
    oficina = es_oficina(request.user)
    visitas = Visita.objects.all() if oficina else visitas_de_campo(request.user)
    visitas = visitas.select_related("cliente", "planta").order_by("-fecha", "hora_desde", "-pk")
    if oficina:
        visitas = visitas.prefetch_related("tecnicos")
    return render(request, "servicios/servicios_tecnicos.html", {
        "pagina": Paginator(visitas, 30).get_page(request.GET.get("page")),
    })


@servicios_requeridos
def detalle(request, pk):
    oficina = es_oficina(request.user)
    visitas = Visita.objects.all() if oficina else visitas_de_campo(request.user)
    visita = get_object_or_404(visitas.select_related("cliente", "planta").prefetch_related("tecnicos"), pk=pk)
    trabajos = visita.trabajos.select_related("responsable", "ticket__equipo_ficha").order_by("pk")
    resultados = visita.resultados.select_related("autor", "responsable")
    if not oficina:
        trabajos = trabajos.filter(responsable=request.user)
        resultados = resultados.filter(trabajo__responsable=request.user)
    por_trabajo = {resultado.trabajo_id: resultado for resultado in resultados}
    fichas = [(trabajo, por_trabajo.get(trabajo.pk)) for trabajo in trabajos]
    return render(request, "servicios/servicio_visita.html", {
        "visita": visita, "fichas": fichas,
        "puede_reportar": Rol.CAMPO in roles(request.user) and request.user in visita.tecnicos.all(),
    })


@campo_requerido
@transaction.atomic
def registrar_resultado(request, visita_id, pk):
    visitas = visitas_de_campo(request.user).select_related("cliente")
    if request.method == "POST":
        visitas = visitas.select_for_update(of=("self",))
    visita = get_object_or_404(visitas, pk=visita_id)
    trabajos = Accion.objects.filter(visitas_agendadas=visita, responsable=request.user)
    if request.method == "POST":
        trabajos = trabajos.select_for_update(of=("self",))
    trabajo = get_object_or_404(trabajos, pk=pk)
    if trabajo.realizada_el or visita.resultados.filter(trabajo=trabajo).exists():
        return redirect("servicio_visita", pk=visita.pk)

    registro = ResultadoTrabajoVisita(visita=visita, trabajo=trabajo, responsable=trabajo.responsable, autor=request.user)
    form = ResultadoForm(request.POST if request.method == "POST" else None, instance=registro)
    if form.is_valid():
        resultado = form.save()
        if resultado.estado == Estado.REALIZADO:
            trabajo.estado = Accion.Estado.REALIZADA
            trabajo.realizada_por = resultado.autor
            trabajo.realizada_el = resultado.registrado_el
            trabajo.motivo_espera = ""
            trabajo.save(update_fields=["estado", "realizada_por", "realizada_el", "motivo_espera"])
        else:
            trabajo.estado = Accion.Estado.EN_ESPERA
            trabajo.motivo_espera = resultado.observacion
            trabajo.save(update_fields=["estado", "motivo_espera"])
            trabajo.cambios.create(autor=resultado.autor, estado=trabajo.estado, motivo=resultado.observacion)
        return redirect("servicio_visita", pk=visita.pk)
    return render(request, "servicios/resultado_visita_form.html", {
        "visita": visita, "trabajo": trabajo, "form": form,
    })
