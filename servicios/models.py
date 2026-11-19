from django.conf import settings
from django.db import models


class Ticket(models.Model):
    asunto = models.CharField(max_length=160)
    cliente = models.CharField(max_length=120)
    equipo = models.CharField(max_length=100, blank=True)
    detalle = models.TextField(blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    creado_el = models.DateTimeField(auto_now_add=True)


class Accion(models.Model):
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
