from django import forms

from .models import Cliente, ContactoCliente, ContratoAbono, DocumentoCliente, Equipo, Planta, RegistroMantenimiento, Ticket


class VinculoTicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ("cliente_ficha", "planta_ficha", "equipo_ficha")
        labels = {"cliente_ficha": "Cliente", "planta_ficha": "Planta", "equipo_ficha": "Equipo"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cliente_ficha"].required = True
        self.fields["planta_ficha"].queryset = Planta.objects.select_related("cliente")
        self.fields["equipo_ficha"].queryset = Equipo.objects.select_related("cliente")

    def clean(self):
        datos = super().clean()
        equipo = datos.get("equipo_ficha")
        if equipo and equipo.planta_id and not datos.get("planta_ficha"):
            datos["planta_ficha"] = equipo.planta
        return datos


class TicketForm(VinculoTicketForm):
    class Meta(VinculoTicketForm.Meta):
        fields = ("asunto", "detalle", "origen", *VinculoTicketForm.Meta.fields)


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ("codigo", "nombre", "tipo", "referencia_sap")


class PlantaForm(forms.ModelForm):
    class Meta:
        model = Planta
        fields = ("cliente", "codigo", "nombre", "direccion")


class EquipoForm(forms.ModelForm):
    class Meta:
        model = Equipo
        fields = ("cliente", "planta", "codigo", "nombre", "numero_serie", "ubicacion")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["planta"].queryset = Planta.objects.select_related("cliente")


class ContactoClienteForm(forms.ModelForm):
    class Meta:
        model = ContactoCliente
        fields = ("nombre", "cargo", "planta", "correo", "telefono")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["planta"].queryset = self.instance.cliente.plantas.all()


class DocumentoClienteForm(forms.ModelForm):
    class Meta:
        model = DocumentoCliente
        fields = ("tipo", "referencia", "descripcion", "enlace")
        help_texts = {"enlace": "Opcional. Usá una dirección HTTP o HTTPS."}

    def clean(self):
        datos = super().clean()
        tipo, referencia = datos.get("tipo"), datos.get("referencia")
        if tipo and referencia:
            existentes = self.instance.cliente.documentos.filter(tipo=tipo, referencia=referencia)
            if existentes.exclude(pk=self.instance.pk).exists():
                self.add_error("referencia", "Ya existe un documento de ese tipo con esta referencia.")
        return datos



class ContratoAbonoForm(forms.ModelForm):
    class Meta:
        model = ContratoAbono
        fields = (
            "referencia", "vigente_desde", "vigente_hasta", "alcance", "frecuencia",
            "cobertura_general", "plantas", "equipos", "valor", "moneda",
            "requiere_oc", "requiere_hes", "portal", "requisitos_administrativos",
        )
        widgets = {
            "vigente_desde": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "vigente_hasta": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "plantas": forms.CheckboxSelectMultiple,
            "equipos": forms.CheckboxSelectMultiple,
        }
        help_texts = {
            "frecuencia": "Por ejemplo, mensual o trimestral.",
            "cobertura_general": "Marcá esta opción si el contrato abarca todo el cliente.",
            "plantas": "Seleccioná las plantas que figuran en el contrato.",
            "equipos": "Seleccioná los equipos incluidos individualmente.",
            "vigente_hasta": "Dejala vacía si el contrato no tiene fecha de fin.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cliente = self.instance.cliente
        self.fields["plantas"].queryset = cliente.plantas.select_related("cliente")
        self.fields["equipos"].queryset = cliente.equipos.select_related("cliente")
        for campo in ("vigente_desde", "vigente_hasta"):
            self.fields[campo].input_formats = ("%Y-%m-%d", "%d/%m/%Y")

    def clean_moneda(self):
        return self.cleaned_data["moneda"].upper()

    def clean(self):
        datos = super().clean()
        if datos.get("cobertura_general") and (datos.get("plantas") or datos.get("equipos")):
            self.add_error("cobertura_general", "Elegí cobertura general o seleccioná plantas y equipos específicos.")
        if not datos.get("cobertura_general") and not (datos.get("plantas") or datos.get("equipos")):
            if "plantas" in datos and "equipos" in datos:
                self.add_error("cobertura_general", "Indicá qué plantas o equipos cubre el contrato, o elegí cobertura general.")
        if datos.get("referencia") and datos.get("vigente_desde"):
            anteriores = self.instance.cliente.contratos_abono.filter(
                referencia=datos["referencia"], vigente_desde=datos["vigente_desde"],
            )
            if anteriores.exclude(pk=self.instance.pk).exists():
                self.add_error("referencia", "Ya existe un contrato con esa referencia y fecha de inicio.")
        return datos



class IdentificacionEquipoForm(forms.ModelForm):
    class Meta:
        model = Equipo
        fields = ("nombre", "numero_serie", "ubicacion")


class RegistroMantenimientoForm(forms.ModelForm):
    class Meta:
        model = RegistroMantenimiento
        fields = (
            "fecha", "visita_realizada", *RegistroMantenimiento.CONTROLES,
            "observaciones", "referencia_sap",
        )
        widgets = {"fecha": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})}
        help_texts = {
            "visita_realizada": "Marcá esta opción si el registro corresponde a una visita que ya se hizo.",
            "observaciones": "Podés anotar mediciones, resultados o qué queda pendiente.",
        }
