from secrets import token_urlsafe

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from .models import Accion, Ticket


class PilotoTest(TestCase):
    def setUp(self):
        self.clave = token_urlsafe(18)
        self.oficina = User.objects.create_user("oficina.prueba", first_name="Inés Prueba", password=self.clave)
        self.oficina.groups.add(Group.objects.create(name="Oficina"))
        self.campo = User.objects.create_user("campo.prueba", first_name="Bruno Prueba", password=self.clave)
        self.otro = User.objects.create_user("otro.prueba", password=self.clave)

    def ingresar(self, usuario):
        self.client.post(reverse("salir"))
        respuesta = self.client.post(reverse("ingresar"), {
            "username": usuario.username, "password": self.clave,
        })
        self.assertRedirects(respuesta, reverse("inicio"))

    def crear_ticket(self):
        self.ingresar(self.oficina)
        respuesta = self.client.post(reverse("nuevo"), {
            "asunto": "Lavado y vibración", "cliente": "Cliente ficticio",
            "equipo": "Generador GE-08", "origen": "Visita",
        })
        ticket = Ticket.objects.get()
        self.assertRedirects(respuesta, reverse("ticket", args=[ticket.pk]))
        return ticket

    def agregar(self, ticket, titulo, responsable, facturacion=Accion.Facturacion.A_DEFINIR):
        respuesta = self.client.post(reverse("agregar", args=[ticket.pk]), {
            "titulo": titulo, "tipo": Accion.Tipo.TAREA, "responsable": responsable.pk,
            "facturacion": facturacion,
        })
        self.assertRedirects(respuesta, reverse("ticket", args=[ticket.pk]))
        return ticket.acciones.get(titulo=titulo)

    def test_recorrido_y_doble_envio(self):
        ticket = self.crear_ticket()
        lavado = self.agregar(ticket, "Lavado incluido en el abono", self.campo, Accion.Facturacion.ABONO)
        revision = self.agregar(ticket, "Revisar vibración", self.oficina)
        detalle = reverse("ticket", args=[ticket.pk])
        realizar = reverse("realizar", args=[lavado.pk])

        self.ingresar(self.otro)
        self.assertNotContains(self.client.get(reverse("inicio")), lavado.titulo)
        self.assertEqual(self.client.get(detalle).status_code, 403)
        self.assertEqual(self.client.post(realizar).status_code, 404)
        self.assertEqual(self.client.post(reverse("agregar", args=[ticket.pk])).status_code, 403)
        lavado.refresh_from_db()
        self.assertIsNone(lavado.realizada_el)

        self.ingresar(self.campo)
        inicio = self.client.get(reverse("inicio"))
        self.assertContains(inicio, lavado.titulo)
        self.assertNotContains(inicio, revision.titulo)
        self.assertEqual(self.client.get(realizar).status_code, 405)
        self.assertRedirects(self.client.post(realizar), reverse("inicio"))
        lavado.refresh_from_db()
        primera_vez = lavado.realizada_el
        self.assertIsNotNone(primera_vez)
        self.assertRedirects(self.client.post(realizar), reverse("inicio"))
        lavado.refresh_from_db()
        self.assertEqual(lavado.realizada_el, primera_vez)
        self.assertEqual(lavado.realizada_por, self.campo)
        self.assertEqual(lavado.facturacion, Accion.Facturacion.ABONO)

        self.ingresar(self.oficina)
        for consulta in (f"T-{ticket.pk}", ticket.asunto, ticket.cliente, ticket.equipo):
            self.assertContains(self.client.get(reverse("inicio"), {"q": consulta}), ticket.asunto)
        self.assertContains(self.client.get(reverse("inicio"), {"responsable": self.oficina.pk}), ticket.asunto)
        self.assertNotContains(self.client.get(reverse("inicio"), {"responsable": self.campo.pk}), ticket.asunto)
        respuesta = self.client.get(detalle)
        for texto in ("Abierto", "Realizada por Bruno Prueba", "sin cargo adicional", revision.titulo, "Inés Prueba"):
            self.assertContains(respuesta, texto)
        revision.refresh_from_db()
        self.assertEqual(revision.responsable, self.oficina)
        self.assertEqual(revision.estado, Accion.Estado.ASIGNADA)
        self.assertIsNone(revision.realizada_el)

    def test_estados_y_motivo_de_espera(self):
        ticket = self.crear_ticket()
        accion = self.agregar(ticket, "Revisar vibración", self.campo)
        url = reverse("cambiar_estado", args=[accion.pk])
        self.ingresar(self.campo)
        self.assertContains(self.client.post(url, {"estado": Accion.Estado.EN_ESPERA}), "Indicá qué falta")
        self.assertEqual(accion.cambios.count(), 0)
        espera = {"estado": Accion.Estado.EN_ESPERA, "motivo": "Informe técnico"}
        self.client.post(url, {"estado": Accion.Estado.EN_CURSO})
        self.client.post(url, espera)
        self.client.post(url, espera)
        self.assertEqual(accion.cambios.count(), 2)
        self.ingresar(self.oficina)
        respuesta = self.client.get(reverse("ticket", args=[ticket.pk]))
        self.assertContains(respuesta, "En espera de: Informe técnico")
        self.assertContains(respuesta, "En curso por Bruno Prueba")
