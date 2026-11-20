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
