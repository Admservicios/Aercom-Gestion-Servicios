from datetime import time, timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Cliente, SolicitudFacturacionTrabajo, Ticket, Visita
from .permisos import Rol


class InicioOficinaTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.oficina = User.objects.create_user("oficina.resumen")
        cls.oficina.groups.add(Group.objects.get_or_create(name=Rol.OFICINA_ANTERIOR)[0])
        cls.coordinacion = User.objects.create_user("coordinacion.resumen")
        cls.coordinacion.groups.add(Group.objects.get_or_create(name=Rol.COORDINACION)[0])
        cls.campo = User.objects.create_user("campo.resumen")
        cls.campo.groups.add(Group.objects.get_or_create(name=Rol.CAMPO)[0])
        cls.abonado = Cliente.objects.create(codigo="OF-01", nombre="Abonado ficticio", tipo=Cliente.Tipo.ABONADO)
        cls.ticket = Ticket.objects.create(
            asunto="Revisión de generador", cliente_ficha=cls.abonado, creado_por=cls.oficina,
        )
        cls.hoy = timezone.localdate()

    def test_resumen_enlaza_los_mismos_registros_que_los_listados(self):
        visita = Visita.objects.create(cliente=self.abonado, fecha=self.hoy, hora_desde=time(8), hora_hasta=time(9))
        otra_visita = Visita.objects.create(
            cliente=self.abonado, fecha=self.hoy + timedelta(days=1), hora_desde=time(8), hora_hasta=time(9),
        )
        pendiente = self.ticket.acciones.create(responsable=self.campo, titulo="Revisar vibración")
        self.ticket.acciones.create(responsable=self.oficina, titulo="Trabajo hecho", realizada_el=timezone.now())
        estados = SolicitudFacturacionTrabajo.Estado
        abierta = self.ticket.solicitudes_facturacion.create(
            solicitante=self.oficina, estado=estados.SOLICITADA, modalidad="posterior",
        )
        en_espera = self.ticket.solicitudes_facturacion.create(
            solicitante=self.coordinacion, estado=estados.EN_ESPERA, modalidad="posterior",
        )
        cerrada = self.ticket.solicitudes_facturacion.create(
            solicitante=self.oficina, estado=estados.FACTURADA, modalidad="posterior",
        )
        self.client.force_login(self.oficina)
        inicio = self.client.get(reverse("inicio"))
        self.assertEqual(list(inicio.context["visitas_hoy"]), [visita])
        self.assertEqual(list(inicio.context["pendientes"]), [pendiente])
        self.assertCountEqual(list(inicio.context["solicitudes_abiertas"]), [abierta, en_espera])
        fecha = self.hoy.isoformat()
        agenda = self.client.get(f"{reverse('agenda')}?dia={fecha}")
        self.assertContains(inicio, f"{reverse('agenda')}?dia={fecha}")
        self.assertEqual(list(agenda.context["visitas"]), [visita])
        self.assertNotContains(agenda, reverse("visita", args=[otra_visita.pk]))
        self.assertContains(inicio, 'href="/pendientes/"')
        self.assertEqual(list(self.client.get(reverse("pendientes")).context["pagina"]), [pendiente])
        url_abiertas = f"{reverse('facturacion_trabajos')}?estado=abiertas"
        self.assertContains(inicio, url_abiertas)
        facturacion = self.client.get(url_abiertas)
        self.assertCountEqual(list(facturacion.context["pagina"]), [abierta, en_espera])
        self.assertNotContains(facturacion, reverse("facturacion_trabajo", args=[cerrada.pk]))

        self.client.force_login(self.coordinacion)
        self.assertEqual(list(self.client.get(reverse("inicio")).context["solicitudes_abiertas"]), [en_espera])
        self.assertEqual(list(self.client.get(url_abiertas).context["pagina"]), [en_espera])
        self.assertEqual(self.client.get(reverse("facturacion_trabajo", args=[abierta.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("facturacion_abonos")).status_code, 403)

    def test_menu_activo_estados_vacios_y_acceso_directo(self):
        self.client.force_login(self.oficina)
        inicio = self.client.get(reverse("inicio"))
        for mensaje in (
            "No hay visitas registradas para hoy.", "No hay acciones pendientes.",
            "No hay solicitudes de facturación abiertas para mostrar.",
        ):
            self.assertContains(inicio, mensaje)
        for vista in ("clientes", "abonados", "terceros", "agenda", "facturacion_trabajos"):
            url = reverse(vista)
            self.assertContains(self.client.get(url), f'href="{url}" aria-current="page"')
        ficha_cliente = reverse("cliente", args=[self.abonado.pk])
        self.assertContains(self.client.get(ficha_cliente), 'href="/clientes/" aria-current="location"')
        propia = self.ticket.acciones.create(responsable=self.campo, titulo="Asignación de campo")
        ajena = self.ticket.acciones.create(responsable=self.oficina, titulo="Asignación de oficina")
        self.client.force_login(self.campo)
        tareas = self.client.get(reverse("inicio"))
        self.assertContains(tareas, propia.titulo)
        self.assertNotContains(tareas, ajena.titulo)
        self.assertNotContains(tareas, 'id="menu-oficina"')
        for vista in ("clientes", "abonados", "terceros", "agenda", "facturacion_trabajos"):
            self.assertEqual(self.client.get(reverse(vista)).status_code, 403)
