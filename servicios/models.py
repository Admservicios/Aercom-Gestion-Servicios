from django.conf import settings
from django.db import models


class Ticket(models.Model):
    asunto = models.CharField(max_length=160)
    cliente = models.CharField(max_length=120)
    origen = models.CharField(max_length=80, blank=True)
    planta = models.CharField(max_length=100, blank=True)
    equipo = models.CharField(max_length=100, blank=True)
    detalle = models.TextField(blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    creado_el = models.DateTimeField(auto_now_add=True)


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
