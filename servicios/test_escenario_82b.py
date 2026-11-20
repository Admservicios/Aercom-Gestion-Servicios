from datetime import timedelta
from io import StringIO

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .management.commands.cargar_demo import CUENTAS
from .management.commands.cargar_escenario_82b import CODIGO
from .models import Accion, Cliente, FacturacionMensualAbono, PedidoServicio


class Escenario82BTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cuentas = {}
        for nombre, (pila, rol) in CUENTAS.items():
            usuario = User.objects.create_user(nombre, first_name=pila, last_name="Demo")
            usuario.groups.add(Group.objects.get_or_create(name=rol)[0])
            cls.cuentas[nombre] = usuario

    def preparar(self, dia):
        salida = StringIO()
        call_command("cargar_escenario_82b", fecha=dia, stdout=salida)
        return salida.getvalue()

    def test_carga_reutilizable_conserva_avance_y_facturacion_por_periodo(self):
        hoy = timezone.localdate()
        reporte = self.preparar(hoy)
        self.assertEqual(reporte, self.preparar(hoy))
        self.assertIn("Pendiente de agendar", reporte)
        self.assertIn("Pendiente de facturar", reporte)

        cliente = Cliente.objects.get(codigo=CODIGO)
        planta = cliente.plantas.get()
        mensual = cliente.facturacion_mensual.get()
        pedido = PedidoServicio.objects.get(ticket__cliente_ficha=cliente)
        visita_ajena = cliente.visitas.get()
        lavado = pedido.ticket.acciones.get()
        correctivo = Accion.objects.get(ticket__cliente_ficha=cliente, tipo=Accion.Tipo.ANALISIS)
        factura_trabajo = visita_ajena.trabajos.get().ticket.solicitudes_facturacion.get()
        self.assertEqual(cliente.equipos.count(), 2)
        self.assertEqual(cliente.tickets.count(), 3)
        self.assertEqual(visita_ajena.fecha, hoy)
        self.assertEqual(visita_ajena.tecnicos.get(), self.cuentas["campo3.demo"])
        self.assertEqual(factura_trabajo.movimientos.count(), 1)
        self.assertEqual(mensual.contrato.equipos.count(), 2)

        self.client.force_login(self.cuentas["coordinacion.demo"])
        origen = reverse("visita_pedido", args=[pedido.pk])
        self.assertContains(self.client.get(origen), f'href="{reverse("pedido_servicio", args=[pedido.pk])}"')
        creada = self.client.post(origen, {
            "fecha": hoy.isoformat(), "hora_desde": "10:30", "hora_hasta": "11:30", "planta": planta.pk,
            "tecnicos": [self.cuentas["campo.demo"].pk], "pedidos": [pedido.pk], "trabajos": [lavado.pk, correctivo.pk],
        })
        visita = pedido.visitas.get()
        self.assertRedirects(creada, reverse("visita", args=[visita.pk]))
        self.client.force_login(self.cuentas["campo.demo"])
        self.assertEqual(self.client.get(reverse("servicio_visita", args=[visita_ajena.pk])).status_code, 404)
        for accion, estado, nota in (
            (lavado, "realizado", ""), (correctivo, "pendiente", "Falta medir con carga para cotizar."),
        ):
            resultado = self.client.post(reverse("resultado_visita", args=[visita.pk, accion.pk]), {
                "estado": estado, "observacion": nota,
            })
            self.assertRedirects(resultado, reverse("servicio_visita", args=[visita.pk]))

        self.client.force_login(self.cuentas["oficina.demo"])
        periodo = reverse("facturacion_abono_mes", args=[hoy.strftime("%Y-%m"), cliente.pk])
        guardada = self.client.post(periodo, {
            "version": mensual.actualizado_el.isoformat(), "estado": "facturada", "importe": mensual.importe,
            "moneda": mensual.moneda, "factura_sap": "FICT-82B-SAP", "fecha_factura": hoy.isoformat(),
        })
        self.assertRedirects(guardada, periodo)
        self.assertIn("Agendado", self.preparar(hoy))
        mensual.refresh_from_db()
        lavado.refresh_from_db()
        correctivo.refresh_from_db()
        factura_trabajo.refresh_from_db()
        self.assertEqual(cliente.tickets.count(), 3)
        self.assertEqual(cliente.visitas.count(), 2)
        self.assertEqual(mensual.estado, FacturacionMensualAbono.Estado.FACTURADA)
        self.assertEqual(factura_trabajo.estado, "solicitada")
        self.assertIsNotNone(lavado.realizada_el)
        self.assertIsNone(correctivo.realizada_el)
        self.assertEqual(correctivo.estado, Accion.Estado.EN_ESPERA)
        self.assertEqual(visita.resultados.count(), 2)

        otra_fecha = hoy.replace(day=1) + timedelta(days=2 if hoy.day == 2 else 1)
        self.preparar(otra_fecha)
        self.assertEqual(cliente.tickets.count(), 6)
        self.assertEqual(cliente.equipos.count(), 2)
        self.assertEqual(cliente.facturacion_mensual.get().pk, mensual.pk)
        self.assertEqual(cliente.contratos_abono.count(), 1)
