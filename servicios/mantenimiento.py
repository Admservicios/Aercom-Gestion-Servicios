from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import IdentificacionEquipoForm, RegistroMantenimientoForm
from .models import Equipo, RegistroMantenimiento
from .permisos import edicion_catalogo_requerida, registro_mantenimiento_requerido


@edicion_catalogo_requerida
def editar_equipo(request, pk):
    equipo = get_object_or_404(Equipo, pk=pk)
    form = IdentificacionEquipoForm(request.POST if request.method == "POST" else None, instance=equipo)
    if form.is_valid():
        form.instance.save(update_fields=IdentificacionEquipoForm.Meta.fields)
        return redirect("equipo", pk=equipo.pk)
    return render(request, "servicios/editar_equipo.html", {
        "equipo": equipo, "form": form, "titulo": "Editar identificación", "texto_boton": "Guardar ficha",
    })


@registro_mantenimiento_requerido
def nuevo_registro(request, pk):
    equipo = get_object_or_404(Equipo, pk=pk)
    form = RegistroMantenimientoForm(
        request.POST if request.method == "POST" else None,
        instance=RegistroMantenimiento(equipo=equipo, registrado_por=request.user),
        initial={"fecha": timezone.localdate()},
    )
    if form.is_valid():
        form.save()
        return redirect("equipo", pk=equipo.pk)
    return render(request, "servicios/editar_equipo.html", {
        "equipo": equipo, "form": form, "titulo": "Registrar mantenimiento", "texto_boton": "Guardar registro",
    })
