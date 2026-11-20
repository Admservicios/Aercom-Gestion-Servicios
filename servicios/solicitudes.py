from django import forms
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import RepuestoSolicitud, SolicitudCotizacion, Ticket
from .permisos import ROLES_REVISION_COTIZACION, ROLES_SOLICITUD_COTIZACION, Rol, requiere_roles, roles


class SolicitudForm(forms.ModelForm):
    class Meta:
        model = SolicitudCotizacion
        fields = (
            "equipos", "referencia_origen", "prioridad", "memoria", "cantidad_tecnicos",
            "horas_por_tecnico", "duracion_estimada", "adicionales",
        )
        widgets = {"equipos": forms.CheckboxSelectMultiple}
        help_texts = {
            "horas_por_tecnico": "Ingresá cero técnicos y cero horas si la mano de obra no aplica.",
            "adicionales": "Indicá traslados, banco de pruebas u otros adicionales, si corresponden.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["equipos"].queryset = self.instance.ticket.cliente_ficha.equipos.select_related("cliente")


RepuestosFormSet = forms.inlineformset_factory(
    SolicitudCotizacion, RepuestoSolicitud,
    fields=("descripcion", "referencia", "cantidad", "por_equipo"),
    extra=1, max_num=50, validate_max=True,
)


class RevisionForm(forms.Form):
    decision = forms.ChoiceField(widget=forms.HiddenInput, choices=[
        (SolicitudCotizacion.Estado.DEVUELTA, "Devolver"),
        (SolicitudCotizacion.Estado.LISTA, "Marcar lista"),
    ])
    nota = forms.CharField(label="Observaciones", required=False, max_length=2000, widget=forms.Textarea)

    def clean(self):
        datos = super().clean()
        if datos.get("decision") == SolicitudCotizacion.Estado.DEVUELTA and not datos.get("nota"):
            self.add_error("nota", "Indicá qué información falta para cotizar.")
        return datos


def solicitudes_visibles(usuario):
    registros = SolicitudCotizacion.objects.all()
    asignados = roles(usuario)
    if asignados & ROLES_REVISION_COTIZACION:
        return registros
    if Rol.RESPONSABLE_TECNICO in asignados:
        return registros.filter(solicitante=usuario)
    return registros.none()


@requiere_roles(ROLES_SOLICITUD_COTIZACION)
def lista(request):
    registros = solicitudes_visibles(request.user).select_related("ticket__cliente_ficha", "solicitante")
    return render(request, "servicios/solicitudes_lista.html", {
        "pagina": Paginator(registros, 30).get_page(request.GET.get("page")),
    })


def detalle_solicitud(request, registro, revision_form=None, error_estado=None):
    puede_revisar = bool(roles(request.user) & ROLES_REVISION_COTIZACION)
    return render(request, "servicios/solicitud_detalle.html", {
        "solicitud": registro,
        "puede_revisar": puede_revisar and registro.estado == SolicitudCotizacion.Estado.ENVIADA,
        "puede_reenviar": (
            registro.solicitante_id == request.user.pk and Rol.RESPONSABLE_TECNICO in roles(request.user)
            and registro.estado == SolicitudCotizacion.Estado.DEVUELTA
        ),
        "revision_form": revision_form or RevisionForm(),
        "error_estado": error_estado,
    })


@requiere_roles(ROLES_SOLICITUD_COTIZACION)
def detalle(request, pk):
    registro = get_object_or_404(
        solicitudes_visibles(request.user).select_related("ticket__cliente_ficha", "solicitante")
        .prefetch_related("equipos", "repuestos", "cambios__autor"),
        pk=pk,
    )
    return detalle_solicitud(request, registro)


def registrar_cambio(solicitud, autor, nota=""):
    solicitud.cambios.create(autor=autor, estado=solicitud.estado, nota=nota)


def guardar_solicitud(request, registro, es_nueva):
    datos = request.POST if request.method == "POST" else None
    inicial = {"equipos": [registro.ticket.equipo_ficha_id]} if es_nueva and registro.ticket.equipo_ficha_id else {}
    form = SolicitudForm(datos, instance=registro, initial=inicial)
    repuestos = RepuestosFormSet(datos, instance=registro)
    form_valido = form.is_valid()
    repuestos_validos = repuestos.is_valid()
    if form_valido and repuestos_validos:
        registro.estado = SolicitudCotizacion.Estado.ENVIADA
        form.save()
        repuestos.save()
        registrar_cambio(registro, request.user)
        return redirect("solicitud_cotizacion", pk=registro.pk)
    return render(request, "servicios/solicitud_form.html", {
        "solicitud": registro, "form": form, "repuestos": repuestos, "es_nueva": es_nueva,
    })


@requiere_roles({Rol.RESPONSABLE_TECNICO})
@transaction.atomic
def nueva(request, ticket_id):
    tickets = Ticket.objects.filter(cliente_ficha__isnull=False)
    if request.method == "POST":
        tickets = tickets.select_for_update()
    ticket = get_object_or_404(tickets, pk=ticket_id)
    return guardar_solicitud(request, SolicitudCotizacion(ticket=ticket, solicitante=request.user), es_nueva=True)


@requiere_roles({Rol.RESPONSABLE_TECNICO})
@transaction.atomic
def reenviar(request, pk):
    solicitudes = SolicitudCotizacion.objects.filter(
        solicitante=request.user, estado=SolicitudCotizacion.Estado.DEVUELTA,
    )
    if request.method == "POST":
        solicitudes = solicitudes.select_for_update()
    registro = get_object_or_404(solicitudes, pk=pk)
    return guardar_solicitud(request, registro, es_nueva=False)


@requiere_roles(ROLES_REVISION_COTIZACION)
@require_POST
@transaction.atomic
def revisar(request, pk):
    registro = get_object_or_404(SolicitudCotizacion.objects.select_for_update(), pk=pk)
    if registro.estado != SolicitudCotizacion.Estado.ENVIADA:
        return detalle_solicitud(request, registro, error_estado="La solicitud ya fue revisada.")
    form = RevisionForm(request.POST)
    if form.is_valid():
        registro.estado = form.cleaned_data["decision"]
        registro.save(update_fields=["estado"])
        registrar_cambio(registro, request.user, form.cleaned_data["nota"])
        return redirect("solicitud_cotizacion", pk=pk)
    return detalle_solicitud(request, registro, form)
