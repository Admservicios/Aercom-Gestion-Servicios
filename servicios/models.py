from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator, URLValidator
from django.db import models
from django.utils import timezone


class Cliente(models.Model):
    class Tipo(models.TextChoices):
        ABONADO = "abonado", "Abonado"
        TERCERO = "tercero", "Tercero"

    codigo = models.CharField("Código", max_length=40, unique=True)
    nombre = models.CharField(max_length=120)
    tipo = models.CharField(max_length=10, choices=Tipo)
    referencia_sap = models.CharField("Referencia SAP", max_length=80, blank=True)

    class Meta:
        ordering = ("nombre", "codigo")

    def __str__(self):
        return f"{self.nombre} ({self.codigo})"


class Planta(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="plantas")
    codigo = models.CharField("Código", max_length=40)
    nombre = models.CharField(max_length=100)
    direccion = models.CharField("Dirección", max_length=200, blank=True)

    class Meta:
        ordering = ("nombre", "codigo")
        constraints = [
            models.UniqueConstraint(fields=("cliente", "codigo"), name="planta_codigo_por_cliente"),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.codigo}) · {self.cliente}"


class ContactoCliente(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="contactos")
    planta = models.ForeignKey(
        Planta, on_delete=models.PROTECT, related_name="contactos", null=True, blank=True,
    )
    nombre = models.CharField(max_length=120)
    cargo = models.CharField(max_length=100, blank=True)
    correo = models.EmailField(blank=True)
    telefono = models.CharField("Teléfono", max_length=40, blank=True)

    class Meta:
        ordering = ("nombre", "pk")

    def clean(self):
        if self.planta_id and self.planta.cliente_id != self.cliente_id:
            raise ValidationError({"planta": "La planta debe pertenecer al cliente del contacto."})


class DocumentoCliente(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="documentos")
    tipo = models.CharField("Tipo de documento", max_length=80)
    referencia = models.CharField(max_length=100)
    descripcion = models.CharField("Descripción", max_length=240, blank=True)
    enlace = models.URLField(
        blank=True, validators=[URLValidator(schemes=["https", "http"])],
    )

    class Meta:
        ordering = ("tipo", "referencia")
        constraints = [
            models.UniqueConstraint(
                fields=("cliente", "tipo", "referencia"), name="documento_tipo_referencia_por_cliente",
            ),
        ]


class Equipo(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="equipos")
    planta = models.ForeignKey(
        Planta, on_delete=models.PROTECT, related_name="equipos", null=True, blank=True,
    )
    codigo = models.CharField("Código", max_length=40)
    nombre = models.CharField(max_length=100)
    numero_serie = models.CharField("Número de serie", max_length=100, blank=True)
    ubicacion = models.CharField("Ubicación", max_length=200, blank=True)

    class Meta:
        ordering = ("nombre", "codigo")
        constraints = [
            models.UniqueConstraint(fields=("cliente", "codigo"), name="equipo_codigo_por_cliente"),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.codigo}) · {self.cliente}"

    def clean(self):
        if self.planta_id and self.planta.cliente_id != self.cliente_id:
            raise ValidationError({"planta": "La planta debe pertenecer al cliente seleccionado."})


class RegistroMantenimiento(models.Model):
    class EstadoControl(models.TextChoices):
        SIN_REGISTRAR = "", "Sin registrar"
        REALIZADO = "realizado", "Realizado"
        PENDIENTE = "pendiente", "Pendiente"
        REQUIERE_ATENCION = "requiere_atencion", "Requiere atención"
        NO_APLICA = "no_aplica", "No aplica"

    CONTROLES = ("bateria", "preventivo", "refrigerante", "combustible", "prueba_con_carga")

    equipo = models.ForeignKey(Equipo, on_delete=models.PROTECT, related_name="registros_mantenimiento")
    fecha = models.DateField("Fecha del registro")
    visita_realizada = models.BooleanField("Corresponde a una visita realizada", default=False)
    bateria = models.CharField("Batería", max_length=20, choices=EstadoControl, blank=True)
    preventivo = models.CharField("Mantenimiento preventivo", max_length=20, choices=EstadoControl, blank=True)
    refrigerante = models.CharField(max_length=20, choices=EstadoControl, blank=True)
    combustible = models.CharField(max_length=20, choices=EstadoControl, blank=True)
    prueba_con_carga = models.CharField(max_length=20, choices=EstadoControl, blank=True)
    observaciones = models.TextField(blank=True)
    referencia_sap = models.CharField("Llamada o referencia SAP", max_length=80, blank=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    registrado_el = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-fecha", "-pk")
        indexes = [models.Index(fields=("equipo", "-fecha", "-id"), name="mantenimiento_equipo_fecha")]

    def clean(self):
        if self.fecha and self.fecha > timezone.localdate():
            raise ValidationError({"fecha": "La fecha del registro no puede ser futura."})
        if not (self.visita_realizada or self.observaciones or self.referencia_sap
                or any(getattr(self, campo) for campo in self.CONTROLES)):
            raise ValidationError("Indicá un control, una visita, una referencia SAP o una observación.")

    def controles_informados(self):
        return [
            (self._meta.get_field(campo).verbose_name, getattr(self, f"get_{campo}_display")())
            for campo in self.CONTROLES
            if getattr(self, campo)
        ]


class ContratoAbono(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="contratos_abono")
    referencia = models.CharField(max_length=80)
    vigente_desde = models.DateField()
    vigente_hasta = models.DateField(blank=True, null=True)
    alcance = models.TextField()
    frecuencia = models.CharField(max_length=120)
    cobertura_general = models.BooleanField("Todas las plantas y equipos", default=False)
    plantas = models.ManyToManyField(Planta, related_name="contratos_abono", blank=True)
    equipos = models.ManyToManyField(Equipo, related_name="contratos_abono", blank=True)
    valor = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    moneda = models.CharField(
        max_length=3, validators=[RegexValidator(r"^[A-Z]{3}\Z", "Ingresá un código como ARS o USD.")],
    )
    requiere_oc = models.BooleanField("Requiere orden de compra (OC)", default=False)
    requiere_hes = models.BooleanField("Requiere hoja de entrada de servicios (HES)", default=False)
    portal = models.CharField(max_length=200, blank=True)
    requisitos_administrativos = models.TextField(blank=True)

    class Meta:
        ordering = ("-vigente_desde", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("cliente", "referencia", "vigente_desde"), name="abono_referencia_inicio_por_cliente",
            ),
            models.CheckConstraint(
                condition=models.Q(vigente_hasta__isnull=True) | models.Q(vigente_hasta__gte=models.F("vigente_desde")),
                name="abono_vigencia_ordenada",
            ),
            models.CheckConstraint(condition=models.Q(valor__gte=0), name="abono_valor_no_negativo"),
        ]

    @property
    def estado_vigencia(self):
        hoy = timezone.localdate()
        if self.vigente_desde > hoy:
            return "Futuro"
        if self.vigente_hasta and self.vigente_hasta < hoy:
            return "Vencido"
        return "Vigente"

    def clean(self):
        errores = {}
        if self.cliente_id and self.cliente.tipo != Cliente.Tipo.ABONADO:
            errores["cliente"] = "Los contratos de abono corresponden a clientes abonados."
        if self.vigente_desde and self.vigente_hasta and self.vigente_hasta < self.vigente_desde:
            errores["vigente_hasta"] = "La fecha de fin debe ser igual o posterior a la de inicio."
        if errores:
            raise ValidationError(errores)


class Ticket(models.Model):
    asunto = models.CharField(max_length=160)
    cliente = models.CharField(max_length=120)
    origen = models.CharField(max_length=80, blank=True)
    planta = models.CharField(max_length=100, blank=True)
    equipo = models.CharField(max_length=100, blank=True)
    cliente_ficha = models.ForeignKey(
        Cliente, on_delete=models.PROTECT, related_name="tickets", null=True, blank=True,
    )
    planta_ficha = models.ForeignKey(
        Planta, on_delete=models.PROTECT, related_name="tickets", null=True, blank=True,
    )
    equipo_ficha = models.ForeignKey(
        Equipo, on_delete=models.PROTECT, related_name="tickets", null=True, blank=True,
    )
    detalle = models.TextField(blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    creado_el = models.DateTimeField(auto_now_add=True)

    @property
    def cliente_nombre(self):
        return self.cliente_ficha.nombre if self.cliente_ficha_id else self.cliente

    @property
    def equipo_nombre(self):
        if self.equipo_ficha_id:
            return self.equipo_ficha.nombre
        return self.equipo

    def clean(self):
        errores = {}
        if self.planta_ficha_id and self.planta_ficha.cliente_id != self.cliente_ficha_id:
            errores["planta_ficha"] = "La planta debe pertenecer al cliente seleccionado."
        if self.equipo_ficha_id:
            equipo = self.equipo_ficha
            if equipo.cliente_id != self.cliente_ficha_id:
                errores["equipo_ficha"] = "El equipo debe pertenecer al cliente seleccionado."
            elif self.planta_ficha_id and equipo.planta_id and equipo.planta_id != self.planta_ficha_id:
                errores["equipo_ficha"] = "El equipo está registrado en otra planta."
        if errores:
            raise ValidationError(errores)


class Accion(models.Model):
    class Estado(models.TextChoices):
        ASIGNADA = "asignada", "Asignada"
        EN_CURSO = "en_curso", "En curso"
        EN_ESPERA = "en_espera", "En espera"
        REALIZADA = "realizada", "Realizada"

    class Tipo(models.TextChoices):
        TAREA = "tarea", "Tarea"
        ANALISIS = "analisis", "Análisis técnico"
        COTIZACION = "cotizacion", "Solicitud de cotización"
        PRESUPUESTO = "presupuesto", "Presupuesto"
        PEDIDO = "pedido", "Pedido de servicio"

    class Facturacion(models.TextChoices):
        A_DEFINIR = "a_definir", "A definir"
        ABONO = "abono", "Incluida en el abono"

    tipo = models.CharField(max_length=16, choices=Tipo, default=Tipo.TAREA)
    facturacion = models.CharField(max_length=16, choices=Facturacion, default=Facturacion.A_DEFINIR)
    estado = models.CharField(max_length=16, choices=Estado, default=Estado.ASIGNADA)
    motivo_espera = models.CharField(max_length=240, blank=True)
    asignada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name="acciones_asignadas",
    )

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="acciones")
    titulo = models.CharField(max_length=160)
    detalle = models.TextField(blank=True)
    responsable = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    asignada_el = models.DateTimeField(auto_now_add=True)
    realizada_el = models.DateTimeField(null=True, blank=True)
    realizada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name="acciones_realizadas",
    )


class CambioAccion(models.Model):
    accion = models.ForeignKey(Accion, on_delete=models.CASCADE, related_name="cambios")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=16, choices=Accion.Estado)
    motivo = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ("pk",)


class AlertaCampo(models.Model):
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="alertas_campo")
    accion = models.ForeignKey(
        Accion, on_delete=models.PROTECT, related_name="alertas", null=True, blank=True,
    )
    detalle = models.TextField(max_length=2000)
    creada_el = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-creada_el", "-pk")


class SolicitudCotizacion(models.Model):
    class Estado(models.TextChoices):
        ENVIADA = "enviada", "En revisión"
        DEVUELTA = "devuelta", "Devuelta para completar"
        LISTA = "lista", "Lista para cotizar"

    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="solicitudes_cotizacion")
    equipos = models.ManyToManyField(Equipo, blank=True, related_name="solicitudes_cotizacion")
    solicitante = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    memoria = models.TextField("Memoria descriptiva y método de trabajo")
    cantidad_tecnicos = models.PositiveSmallIntegerField("Cantidad de técnicos")
    horas_por_tecnico = models.DecimalField(
        "Horas estimadas por técnico", max_digits=6, decimal_places=2, validators=[MinValueValidator(0)],
    )
    duracion_estimada = models.DecimalField(
        "Duración estimada de la intervención (horas)", max_digits=6, decimal_places=2,
        blank=True, null=True, validators=[MinValueValidator(Decimal("0.01"))],
    )
    adicionales = models.TextField(blank=True)
    referencia_origen = models.CharField("Llamada SAP o referencia de origen", max_length=120, blank=True)
    prioridad = models.CharField("Prioridad o indicación para la visita", max_length=160, blank=True)
    estado = models.CharField(max_length=10, choices=Estado, default=Estado.ENVIADA)
    creada_el = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-creada_el", "-pk")

    def clean(self):
        if (
            self.cantidad_tecnicos is not None and self.horas_por_tecnico is not None
            and bool(self.cantidad_tecnicos) != bool(self.horas_por_tecnico)
        ):
            raise ValidationError({"horas_por_tecnico": "Indicá técnicos y horas, o ingresá cero en ambos campos."})

    @property
    def horas_totales(self):
        return self.cantidad_tecnicos * self.horas_por_tecnico


class RepuestoSolicitud(models.Model):
    solicitud = models.ForeignKey(SolicitudCotizacion, on_delete=models.CASCADE, related_name="repuestos")
    descripcion = models.CharField("Descripción", max_length=160)
    referencia = models.CharField("Código o referencia", max_length=80, blank=True)
    cantidad = models.DecimalField(max_digits=9, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    por_equipo = models.BooleanField("Cantidad por equipo", default=False)

    class Meta:
        ordering = ("pk",)


class CambioSolicitud(models.Model):
    solicitud = models.ForeignKey(SolicitudCotizacion, on_delete=models.CASCADE, related_name="cambios")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    estado = models.CharField(max_length=10, choices=SolicitudCotizacion.Estado)
    nota = models.TextField(blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-pk",)
