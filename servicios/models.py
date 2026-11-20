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
    documentos = models.ManyToManyField(DocumentoCliente, related_name="tickets", blank=True)
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


class CategoriaEspera(models.TextChoices):
    CLIENTE = "cliente", "Cliente"
    COMPRAS = "compras", "Compras"
    DOCUMENTACION = "documentacion", "Documentación"
    OTRA = "otra", "Otra espera"


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
    categoria_espera = models.CharField(
        "Motivo de espera", max_length=16, choices=CategoriaEspera, blank=True,
    )
    proximo_paso = models.CharField("Próximo paso", max_length=240, blank=True)
    depende_de = models.ForeignKey(
        "self", on_delete=models.RESTRICT, null=True, blank=True, related_name="acciones_siguientes",
        verbose_name="Acción previa",
    )
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

    def clean(self):
        if self.depende_de_id and self.depende_de.ticket_id != self.ticket_id:
            raise ValidationError({"depende_de": "La acción previa debe pertenecer al mismo ticket."})

    @property
    def bloqueada_por_previa(self):
        return self.depende_de_id is not None and self.depende_de.realizada_el is None

    @property
    def siguiente_paso(self):
        if self.realizada_el:
            return "Acción realizada"
        if self.bloqueada_por_previa:
            return f"Esperar que se complete «{self.depende_de.titulo}»"
        return self.proximo_paso or self.motivo_espera or "Por definir"


class CambioAccion(models.Model):
    accion = models.ForeignKey(Accion, on_delete=models.CASCADE, related_name="cambios")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=16, choices=Accion.Estado)
    motivo = models.CharField(max_length=240, blank=True)
    proximo_paso = models.CharField(max_length=240, blank=True, null=True)

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


class Cotizacion(models.Model):
    class Estado(models.TextChoices):
        PREPARACION = "preparacion", "En preparación"
        ENVIADA = "enviada", "Enviada"
        APROBADA = "aprobada", "Aprobada"
        RECHAZADA = "rechazada", "Rechazada"

    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="cotizaciones")
    solicitud = models.ForeignKey(
        SolicitudCotizacion, on_delete=models.PROTECT, related_name="cotizaciones", blank=True, null=True,
    )
    referencia = models.CharField("Referencia de presupuesto", max_length=100, blank=True)
    alcance = models.TextField()
    importe = models.DecimalField(
        max_digits=14, decimal_places=2, blank=True, null=True, validators=[MinValueValidator(0)],
    )
    moneda = models.CharField(
        max_length=3, blank=True, validators=[RegexValidator(r"^[A-Z]{3}\Z", "Ingresá un código como ARS o USD.")],
    )
    estado = models.CharField(max_length=12, choices=Estado, default=Estado.PREPARACION)
    confirmacion_correo = models.CharField("Referencia de confirmación por correo", max_length=240, blank=True)
    orden_compra = models.CharField("Número o referencia de OC recibida", max_length=120, blank=True)

    class Meta:
        ordering = ("-pk",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(importe__gte=0) | models.Q(importe__isnull=True), name="cotizacion_importe_no_negativo",
            ),
        ]

    def clean(self):
        if self.solicitud_id and self.solicitud.ticket_id != self.ticket_id:
            raise ValidationError({"solicitud": "La solicitud técnica debe corresponder al ticket de la cotización."})


class CambioCotizacion(models.Model):
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.CASCADE, related_name="cambios")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    estado = models.CharField(max_length=12, choices=Cotizacion.Estado)
    nota = models.TextField(blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-pk",)


class SolicitudPrecio(models.Model):
    codigo = models.CharField("Código", max_length=80, blank=True)
    descripcion = models.CharField("Descripción del repuesto o insumo", max_length=160)
    destinatario = models.CharField(max_length=120)
    solicitada_el = models.DateField("Fecha de solicitud")
    solicitante = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    cotizacion = models.ForeignKey(
        Cotizacion, on_delete=models.PROTECT, blank=True, null=True, related_name="solicitudes_precio",
    )
    repuesto = models.ForeignKey(
        RepuestoSolicitud, on_delete=models.SET_NULL, blank=True, null=True, related_name="solicitudes_precio",
    )
    anterior = models.ForeignKey(
        "self", on_delete=models.PROTECT, blank=True, null=True, related_name="actualizaciones",
    )

    class Meta:
        ordering = ("-solicitada_el", "-pk")

    def clean(self):
        if self.solicitada_el and self.solicitada_el > timezone.localdate():
            raise ValidationError({"solicitada_el": "La fecha de solicitud no puede ser futura."})
        if self.solicitada_el and self.anterior_id and self.solicitada_el < self.anterior.solicitada_el:
            raise ValidationError({"solicitada_el": "La actualización no puede ser anterior a la solicitud previa."})


class RespuestaPrecio(models.Model):
    solicitud = models.ForeignKey(SolicitudPrecio, on_delete=models.PROTECT, related_name="respuestas")
    recibida_el = models.DateField("Fecha de respuesta")
    fuente = models.CharField("Proveedor o fuente", max_length=160)
    precio = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    moneda = models.CharField(
        max_length=3, validators=[RegexValidator(r"^[A-Z]{3}\Z", "Ingresá un código como ARS o USD.")],
    )
    vigente_hasta = models.DateField("Vigente hasta", blank=True, null=True)
    respuesta = models.TextField("Detalle o referencia de la respuesta", blank=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    registrado_el = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-recibida_el", "-pk")
        constraints = [
            models.CheckConstraint(condition=models.Q(precio__gte=0), name="respuesta_precio_no_negativo"),
            models.CheckConstraint(
                condition=models.Q(vigente_hasta__isnull=True) | models.Q(vigente_hasta__gte=models.F("recibida_el")),
                name="respuesta_precio_vigencia_ordenada",
            ),
        ]

    def clean(self):
        errores = {}
        if self.recibida_el:
            if self.recibida_el > timezone.localdate():
                errores["recibida_el"] = "La fecha de respuesta no puede ser futura."
            elif self.solicitud_id and self.recibida_el < self.solicitud.solicitada_el:
                errores["recibida_el"] = "La respuesta no puede ser anterior a la solicitud."
            if self.vigente_hasta and self.vigente_hasta < self.recibida_el:
                errores["vigente_hasta"] = "La vigencia no puede terminar antes de la respuesta."
        if errores:
            raise ValidationError(errores)


class PedidoServicio(models.Model):
    class Tipo(models.TextChoices):
        SERVICIO = "servicio", "Servicio"
        REPUESTOS = "repuestos", "Venta de repuestos"

    class Estado(models.TextChoices):
        PREPARACION = "preparacion", "En preparación"
        ENVIADO = "enviado", "Enviado"
        PENDIENTE_AGENDAR = "pendiente_agendar", "Pendiente de agendar"
        AGENDADO = "agendado", "Agendado"
        ENTREGADO = "entregado", "Entregado"

    class ModalidadEntrega(models.TextChoices):
        RETIRO = "retiro", "Retiro en depósito"
        ENVIO = "envio", "Envío"

    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="pedidos_servicio")
    cotizaciones = models.ManyToManyField(Cotizacion, related_name="pedidos_servicio", blank=True)
    contrato = models.ForeignKey(
        ContratoAbono, on_delete=models.PROTECT, related_name="pedidos_servicio", blank=True, null=True,
    )
    equipos = models.ManyToManyField(Equipo, related_name="pedidos_servicio", blank=True)
    referencia = models.CharField("Referencia del pedido", max_length=100, blank=True)
    tipo = models.CharField(max_length=10, choices=Tipo, default=Tipo.SERVICIO)
    alcance = models.TextField()
    indicaciones = models.TextField("Indicaciones y próxima acción", blank=True)
    modalidad_entrega = models.CharField(max_length=8, choices=ModalidadEntrega, blank=True)
    estado = models.CharField(max_length=18, choices=Estado, default=Estado.PREPARACION)
    fecha_agendada = models.DateField(blank=True, null=True)

    class Meta:
        ordering = ("-pk",)

    @property
    def destino(self):
        return "Logística" if self.tipo == self.Tipo.REPUESTOS else "Coordinación"

    @property
    def siguiente_paso(self):
        if self.estado == self.Estado.PREPARACION:
            return f"Enviar a {self.destino}"
        if self.tipo == self.Tipo.REPUESTOS:
            return "Entrega registrada" if self.estado == self.Estado.ENTREGADO else "Esperar confirmación de Logística"
        if self.estado == self.Estado.AGENDADO:
            return "Realizar el servicio según la Agenda General"
        return "Confirmar la programación en la Agenda General"


class CambioPedidoServicio(models.Model):
    pedido = models.ForeignKey(PedidoServicio, on_delete=models.CASCADE, related_name="cambios")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    estado = models.CharField(max_length=18, choices=PedidoServicio.Estado)
    nota = models.TextField(blank=True)
    referencia = models.CharField(max_length=180, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-pk",)


class Visita(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="visitas")
    planta = models.ForeignKey(Planta, on_delete=models.PROTECT, related_name="visitas", null=True, blank=True)
    pedidos = models.ManyToManyField(PedidoServicio, related_name="visitas", blank=True)
    trabajos = models.ManyToManyField(Accion, related_name="visitas_agendadas", blank=True)
    tecnicos = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="visitas_asignadas")
    fecha = models.DateField()
    hora_desde = models.TimeField("Hora de inicio")
    hora_hasta = models.TimeField("Hora de fin")
    referencia_excel = models.CharField("Referencia en la Agenda General", max_length=150, blank=True)
    indicaciones = models.TextField(blank=True)

    class Meta:
        ordering = ("fecha", "hora_desde", "pk")
        indexes = [models.Index(fields=("fecha", "hora_desde"), name="visita_fecha_horario")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(hora_hasta__gt=models.F("hora_desde")), name="visita_horario_ordenado",
            ),
        ]

    def clean(self):
        errores = {}
        if self.hora_desde and self.hora_hasta and self.hora_hasta <= self.hora_desde:
            errores["hora_hasta"] = "La hora de fin debe ser posterior a la de inicio."
        if self.planta_id and self.planta.cliente_id != self.cliente_id:
            errores["planta"] = "La planta debe pertenecer al cliente de la visita."
        if errores:
            raise ValidationError(errores)


class MovimientoAgenda(models.Model):
    visita = models.ForeignKey(Visita, on_delete=models.CASCADE, related_name="movimientos")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateField()
    hora_desde = models.TimeField()
    hora_hasta = models.TimeField()
    referencia_excel = models.CharField(max_length=150, blank=True)
    motivo = models.CharField(max_length=300, blank=True)
    registrado_el = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-pk",)


class ResultadoTrabajoVisita(models.Model):
    class Estado(models.TextChoices):
        REALIZADO = "realizado", "Realizado"
        PARCIAL = "parcial", "Parcial"
        PENDIENTE = "pendiente", "Pendiente"

    visita = models.ForeignKey(Visita, on_delete=models.PROTECT, related_name="resultados")
    trabajo = models.ForeignKey(Accion, on_delete=models.PROTECT, related_name="resultados_visita")
    responsable = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    estado = models.CharField(max_length=10, choices=Estado)
    observacion = models.CharField("Observación", max_length=240, blank=True)
    referencia_sap = models.CharField("Reporte o llamada SAP", max_length=100, blank=True)
    registrado_el = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("visita", "trabajo"), name="resultado_unico_por_visita_y_trabajo"),
        ]


class FacturacionMensualAbono(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente de facturar"
        FACTURADA = "facturada", "Facturada"
        NO_CORRESPONDE = "no_corresponde", "No corresponde"

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="facturacion_mensual")
    periodo = models.DateField()
    contrato = models.ForeignKey(ContratoAbono, on_delete=models.PROTECT, blank=True, null=True)
    estado = models.CharField(max_length=14, choices=Estado, default=Estado.PENDIENTE)
    fecha_prevista = models.DateField("Fecha prevista de facturación", blank=True, null=True)
    modalidad = models.CharField("Modalidad de facturación", max_length=140, blank=True)
    importe = models.DecimalField(
        max_digits=14, decimal_places=2, blank=True, null=True, validators=[MinValueValidator(0)],
    )
    moneda = models.CharField(
        max_length=3, blank=True, validators=[RegexValidator(r"^[A-Z]{3}\Z", "Ingresá un código como ARS o USD.")],
    )
    ajuste = models.CharField("Ajuste aplicado o criterio", max_length=240, blank=True)
    requiere_oc = models.BooleanField("Requiere orden de compra (OC)", default=False)
    requiere_hes = models.BooleanField("Requiere hoja de entrada de servicios (HES)", default=False)
    orden_compra = models.CharField("Referencia OC", max_length=120, blank=True)
    hes = models.CharField("Referencia HES", max_length=120, blank=True)
    portal = models.CharField(max_length=200, blank=True)
    observaciones = models.TextField(blank=True)
    factura_sap = models.CharField("Referencia de factura en SAP", max_length=120, blank=True)
    fecha_factura = models.DateField("Fecha de emisión en SAP", blank=True, null=True)
    actualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    actualizado_el = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-periodo", "-pk")
        constraints = [
            models.UniqueConstraint(fields=("cliente", "periodo"), name="facturacion_abono_unica_por_periodo"),
            models.CheckConstraint(condition=models.Q(periodo__day=1), name="facturacion_abono_inicio_de_mes"),
            models.CheckConstraint(
                condition=models.Q(importe__gte=0) | models.Q(importe__isnull=True), name="facturacion_abono_importe_no_negativo",
            ),
        ]

    def clean(self):
        errores = {}
        if self.estado != self.Estado.NO_CORRESPONDE and not self.contrato_id:
            errores["estado"] = "Seleccioná un contrato del período para registrar facturación."
        if self.contrato_id and self.contrato.cliente_id != self.cliente_id:
            errores["estado"] = "El contrato debe pertenecer al cliente de la facturación."
        if self.estado == self.Estado.NO_CORRESPONDE and not self.observaciones:
            errores["observaciones"] = "Indicá por qué no corresponde facturar este período."
        if self.estado == self.Estado.FACTURADA:
            if not self.factura_sap:
                errores["factura_sap"] = "Ingresá la referencia de la factura emitida en SAP."
            if not self.fecha_factura:
                errores["fecha_factura"] = "Ingresá la fecha de emisión."
            if self.importe is None:
                errores["importe"] = "Ingresá el importe facturado."
            if not self.moneda:
                errores["moneda"] = "Ingresá la moneda de la factura."
        elif self.factura_sap or self.fecha_factura:
            errores["estado"] = "Marcá Facturada si ya registraste el comprobante de SAP."
        if self.fecha_factura and self.fecha_factura > timezone.localdate():
            errores["fecha_factura"] = "La fecha de emisión no puede ser futura."
        if errores:
            raise ValidationError(errores)


class SolicitudFacturacionTrabajo(models.Model):
    class Modalidad(models.TextChoices):
        PREVIA = "previa", "Antes de la ejecución"
        POSTERIOR = "posterior", "Después de la ejecución"
        ABONO = "abono", "Incluida en el abono"

    class Estado(models.TextChoices):
        SOLICITADA = "solicitada", "Solicitada"
        EN_ESPERA = "en_espera", "Documentación pendiente"
        FACTURADA = "facturada", "Facturada"
        CUBIERTA = "cubierta", "Cubierta por el abono"

    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="solicitudes_facturacion")
    pedido = models.ForeignKey(
        PedidoServicio, on_delete=models.PROTECT, blank=True, null=True, related_name="solicitudes_facturacion",
    )
    cotizacion = models.ForeignKey(
        Cotizacion, on_delete=models.PROTECT, blank=True, null=True, related_name="solicitudes_facturacion",
    )
    trabajos = models.ManyToManyField(Accion, related_name="solicitudes_facturacion", blank=True)
    solicitante = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    creada_el = models.DateTimeField(auto_now_add=True)
    modalidad = models.CharField(max_length=10, choices=Modalidad)
    estado = models.CharField(max_length=12, choices=Estado, default=Estado.SOLICITADA)
    referencia_presupuesto = models.CharField("Referencia de presupuesto", max_length=120, blank=True)
    orden_compra = models.CharField("Referencia de OC", max_length=120, blank=True)
    correo_envio = models.EmailField("Correo de envío", blank=True)
    centro_costo = models.CharField("Centro de costo", max_length=100, blank=True)
    moneda = models.CharField(
        max_length=3, blank=True, validators=[RegexValidator(r"^[A-Z]{3}\Z", "Ingresá un código como ARS o USD.")],
    )
    referencia_cambio = models.CharField("Cambio o referencia cambiaria", max_length=120, blank=True)
    tipo_comprobante = models.CharField(max_length=100, blank=True)
    hes = models.CharField("Referencia HES", max_length=120, blank=True)
    portal = models.CharField(max_length=200, blank=True)
    documentacion_faltante = models.TextField("Documentación faltante", blank=True)
    observaciones = models.TextField(blank=True)
    factura_sap = models.CharField("Referencia de factura en SAP", max_length=120, blank=True)
    fecha_factura = models.DateField("Fecha de emisión en SAP", blank=True, null=True)
    cobranza_aplica = models.BooleanField("Corresponde seguir la cobranza", default=False)
    referencia_cobro = models.CharField("Referencia de cobro", max_length=120, blank=True)
    fecha_cobro = models.DateField(blank=True, null=True)

    class Meta:
        ordering = ("-pk",)

    @property
    def estado_cobranza(self):
        if not self.cobranza_aplica:
            return "No aplica"
        return "Cobrada" if self.fecha_cobro else "Pendiente de cobro"

    def actualizar_estado(self):
        if self.modalidad == self.Modalidad.ABONO:
            self.estado = self.Estado.CUBIERTA
        elif self.factura_sap:
            self.estado = self.Estado.FACTURADA
        elif self.documentacion_faltante:
            self.estado = self.Estado.EN_ESPERA
        else:
            self.estado = self.Estado.SOLICITADA

    def clean(self):
        errores = {}
        if self.modalidad == self.Modalidad.ABONO and self.ticket_id:
            if self.ticket.cliente_ficha.tipo != Cliente.Tipo.ABONADO:
                errores["modalidad"] = "La cobertura del abono solo corresponde a clientes abonados."
            if self.factura_sap or self.fecha_factura:
                errores["factura_sap"] = "Un trabajo cubierto por el abono no lleva una factura puntual."
            if self.cobranza_aplica:
                errores["cobranza_aplica"] = "Un trabajo cubierto por el abono no tiene cobranza puntual."
        if self.factura_sap and not self.fecha_factura:
            errores["fecha_factura"] = "Ingresá la fecha de emisión en SAP."
        if self.fecha_factura and not self.factura_sap:
            errores["factura_sap"] = "Ingresá la referencia del comprobante en SAP."
        if self.fecha_factura and self.fecha_factura > timezone.localdate():
            errores["fecha_factura"] = "La fecha de emisión no puede ser futura."
        if self.fecha_cobro or self.referencia_cobro:
            if not self.cobranza_aplica:
                errores["cobranza_aplica"] = "Indicá que corresponde seguir la cobranza."
            if not self.fecha_cobro:
                errores["fecha_cobro"] = "Ingresá la fecha de cobro."
            elif self.fecha_cobro > timezone.localdate():
                errores["fecha_cobro"] = "La fecha de cobro no puede ser futura."
            if not self.referencia_cobro:
                errores["referencia_cobro"] = "Ingresá la referencia del cobro."
        if errores:
            raise ValidationError(errores)


class MovimientoFacturacionTrabajo(models.Model):
    solicitud = models.ForeignKey(SolicitudFacturacionTrabajo, on_delete=models.CASCADE, related_name="movimientos")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    estado = models.CharField(max_length=12, choices=SolicitudFacturacionTrabajo.Estado)
    nota = models.TextField(blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-pk",)


class LlamadaServicioSAP(models.Model):
    class Circuito(models.TextChoices):
        PUNTUAL = "puntual", "Trabajo facturado por separado"
        ABONO = "abono", "Visita de abono"

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="llamadas_sap")
    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="llamadas_sap")
    visita = models.ForeignKey(Visita, on_delete=models.PROTECT, blank=True, null=True, related_name="llamadas_sap")
    facturaciones = models.ManyToManyField(SolicitudFacturacionTrabajo, blank=True, related_name="llamadas_sap")
    referencia = models.CharField("Número o referencia de llamada en SAP", max_length=100)
    circuito = models.CharField(max_length=10, choices=Circuito)
    observaciones = models.TextField(blank=True)
    registrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    registrada_el = models.DateTimeField(auto_now_add=True)
    cerrada_en_sap = models.DateField("Fecha efectiva del cierre en SAP", blank=True, null=True)
    cierre_registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, blank=True, null=True, related_name="+",
    )
    cierre_registrado_el = models.DateTimeField(blank=True, null=True)
    observacion_cierre = models.TextField("Observación del cierre", blank=True)
    respaldo_facturas = models.TextField(blank=True)

    class Meta:
        ordering = ("-pk",)
        constraints = [
            models.UniqueConstraint(fields=("cliente", "referencia"), name="llamada_sap_unica_por_cliente"),
        ]


class MovimientoTiempoAccion(models.Model):
    class Tipo(models.TextChoices):
        ASIGNACION = "asignacion", "Asignada"
        TOMA = "toma", "Tomada o retomada"
        ESPERA = "espera", "En espera"
        DERIVACION = "derivacion", "Derivada"
        FINALIZACION = "finalizacion", "Completada"

    accion = models.ForeignKey(Accion, on_delete=models.CASCADE, related_name="movimientos_tiempo")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    responsable = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    puesto = models.CharField(max_length=70)
    tipo = models.CharField(max_length=12, choices=Tipo)
    categoria_espera = models.CharField(max_length=16, choices=CategoriaEspera, blank=True)
    motivo = models.CharField(max_length=240, blank=True)
    ocurrio_el = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("ocurrio_el", "pk")
        indexes = [models.Index(fields=("accion", "ocurrio_el"), name="tiempo_accion_fecha")]


class Recordatorio(models.Model):
    class Tipo(models.TextChoices):
        SEGUIMIENTO = "seguimiento", "Seguimiento"
        VENCIMIENTO = "vencimiento", "Vencimiento"
        DEMORA = "demora", "Demora"

    class Disparador(models.TextChoices):
        FECHA = "fecha", "Por fecha"
        PROXIMA_VISITA = "proxima_visita", "En la próxima visita"

    titulo = models.CharField("Título", max_length=160)
    detalle = models.TextField(blank=True)
    tipo = models.CharField(max_length=12, choices=Tipo, default=Tipo.SEGUIMIENTO)
    disparador = models.CharField(max_length=14, choices=Disparador)
    fecha = models.DateField(blank=True, null=True)
    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, null=True, blank=True, related_name="recordatorios")
    visita = models.ForeignKey(Visita, on_delete=models.PROTECT, null=True, blank=True, related_name="recordatorios")
    responsable = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    creado_el = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-pk",)
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(disparador="fecha", fecha__isnull=False, visita__isnull=True)
                    | models.Q(disparador="proxima_visita", fecha__isnull=True, ticket__isnull=False)
                ),
                name="recordatorio_disparador_valido",
            ),
        ]

    @property
    def fecha_activacion(self):
        return self.visita.fecha if self.visita_id else self.fecha


class AvisoOperativo(models.Model):
    recordatorio = models.OneToOneField(
        Recordatorio, on_delete=models.PROTECT, blank=True, null=True, related_name="aviso",
    )
    alerta_campo = models.OneToOneField(
        AlertaCampo, on_delete=models.PROTECT, blank=True, null=True, related_name="aviso",
    )
    atendido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, blank=True, null=True, related_name="+",
    )
    atendido_el = models.DateTimeField(blank=True, null=True)
    resuelto_el = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-pk",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(recordatorio__isnull=False, alerta_campo__isnull=True)
                | models.Q(recordatorio__isnull=True, alerta_campo__isnull=False),
                name="aviso_origen_unico",
            ),
        ]

    @property
    def titulo(self):
        return self.recordatorio.titulo if self.recordatorio_id else "Novedad de Campo"


class RecepcionAviso(models.Model):
    aviso = models.ForeignKey(AvisoOperativo, on_delete=models.CASCADE, related_name="recepciones")
    destinatario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="avisos_recibidos")
    activo = models.BooleanField(default=True)
    visto_el = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("aviso", "destinatario"), name="aviso_destinatario_unico"),
        ]
