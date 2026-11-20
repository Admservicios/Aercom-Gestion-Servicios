from django import forms
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import redirect, render

from .models import Accion, AlertaCampo
from .permisos import campo_requerido, es_oficina, servicios_requeridos
from .recordatorios import avisar_novedad_campo


class AlertaCampoForm(forms.ModelForm):
    class Meta:
        model = AlertaCampo
        fields = ("accion", "detalle")
        labels = {"accion": "Tarea relacionada (opcional)", "detalle": "Qué detectaste"}

    def __init__(self, usuario, *args, **kwargs):
        super().__init__(*args, **kwargs)
        campo = self.fields["accion"]
        campo.queryset = Accion.objects.filter(responsable=usuario).order_by("-asignada_el", "-pk")
        campo.label_from_instance = lambda accion: f"T-{accion.ticket_id} · {accion.titulo}"


@servicios_requeridos
def alertas(request):
    oficina = es_oficina(request.user)
    registros = AlertaCampo.objects.select_related("autor", "accion", "aviso")
    if not oficina:
        registros = registros.filter(autor=request.user)
    return render(request, "servicios/alertas.html", {
        "pagina": Paginator(registros, 50).get_page(request.GET.get("page")),
    })


@campo_requerido
@transaction.atomic
def nueva_alerta(request):
    form = AlertaCampoForm(request.user, request.POST if request.method == "POST" else None)
    if form.is_valid():
        registro = form.save(commit=False)
        registro.autor = request.user
        registro.save()
        avisar_novedad_campo(registro)
        return redirect("alertas")
    return render(request, "servicios/alta_ficha.html", {
        "form": form, "titulo": "Reportar alerta", "texto_boton": "Registrar alerta",
    })
