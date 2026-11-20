from django import forms

from .models import Cliente, ContactoCliente, DocumentoCliente, Equipo, Planta, Ticket


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
        fields = ("cliente", "planta", "codigo", "nombre", "numero_serie")

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
