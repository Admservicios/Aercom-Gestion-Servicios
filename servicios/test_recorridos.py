from datetime import timedelta
from secrets import token_urlsafe

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Accion, Cliente, Cotizacion, PedidoServicio, SolicitudFacturacionTrabajo, Ticket
from .permisos import Rol


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class RecorridosDeServiciosTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.clave = token_urlsafe(18)
        funciones = {
            "admin": Rol.ADMINISTRACION, "comercial": Rol.COMERCIAL, "tecnica": Rol.RESPONSABLE_TECNICO,
            "coordinacion": Rol.COORDINACION, "campo": Rol.CAMPO, "otro_campo": Rol.CAMPO,
        }
        cls.usuarios = {}
        for nombre, rol in funciones.items():
            usuario = User.objects.create_user(f"{nombre}.recorrido", password=cls.clave)
            usuario.groups.add(Group.objects.get_or_create(name=rol)[0])
            cls.usuarios[nombre] = usuario

    def setUp(self):
        self.hoy = timezone.localdate()
        self.sesiones = {nombre: Client() for nombre in self.usuarios}
        for nombre, usuario in self.usuarios.items():
            respuesta = self.sesiones[nombre].post(reverse("ingresar"), {
                "username": usuario.username, "password": self.clave,
            })
            self.assertRedirects(respuesta, reverse("inicio"), fetch_redirect_response=False)

    def post(self, rol, vista, datos=None, *args):
        respuesta = self.sesiones[rol].post(reverse(vista, args=args), datos or {})
        form = respuesta.context.get("form") if respuesta.context else None
        errores = form.errors.as_text() if form is not None else ""
        self.assertEqual(respuesta.status_code, 302, f"{vista} · {errores}")
        return respuesta

    def crear_cliente(self, nombre, tipo):
        self.post("admin", "nuevo_cliente", {"codigo": nombre.upper(), "nombre": nombre, "tipo": tipo})
        return Cliente.objects.get(nombre=nombre)

    def ticket(self, cliente, asunto, planta=None, equipo=None):
        datos = {"asunto": asunto, "cliente_ficha": cliente.pk}
        if planta:
            datos["planta_ficha"] = planta.pk
        if equipo:
            datos["equipo_ficha"] = equipo.pk
        self.post("admin", "nuevo", datos)
        return Ticket.objects.get(asunto=asunto)

    def accion(self, ticket, titulo, facturacion=Accion.Facturacion.A_DEFINIR):
        self.post("admin", "agregar", {
            "titulo": titulo, "tipo": "tarea", "responsable": self.usuarios["campo"].pk, "facturacion": facturacion,
        }, ticket.pk)
        return ticket.acciones.get(titulo=titulo)

    def cotizar(self, ticket, desde=None):
        vista = "cotizar_solicitud" if desde else "nueva_cotizacion"
        self.post("comercial", vista, {
            "referencia": f"PRES-FICTICIO-{ticket.pk}", "alcance": "Alcance ficticio aprobado",
            "importe": "15000.50", "moneda": "ARS",
        }, (desde or ticket).pk)
        cotizacion = ticket.cotizaciones.get()
        self.post("comercial", "enviar_cotizacion", {}, cotizacion.pk)
        self.post("comercial", "respuesta_cotizacion", {
            "decision": "aprobada", "confirmacion_correo": "Confirmación ficticia del cliente", "orden_compra": "OC-FICTICIA",
        }, cotizacion.pk)
        cotizacion.refresh_from_db()
        self.assertEqual(cotizacion.estado, Cotizacion.Estado.APROBADA)
        return cotizacion

    def pedido(self, cotizacion, tipo="servicio", modalidad_entrega=""):
        self.post("admin", "pedido_desde_cotizacion", {
            "referencia": f"PED-FICTICIO-{cotizacion.pk}", "alcance": cotizacion.alcance,
            "cotizaciones": [cotizacion.pk], "tipo": tipo, "modalidad_entrega": modalidad_entrega,
        }, cotizacion.pk)
        pedido = cotizacion.pedidos_servicio.get()
        self.post("admin", "seguimiento_pedido", {"estado": "enviado", "referencia": "Envío ficticio registrado"}, pedido.pk)
        pedido.refresh_from_db()
        return pedido

    def visita(self, pedido, trabajos, pedidos_adicionales=(), planta=None):
        datos = {
            "fecha": self.hoy.isoformat(), "hora_desde": "09:00", "hora_hasta": "11:00",
            "tecnicos": [self.usuarios["campo"].pk],
            "pedidos": [pedido.pk, *(item.pk for item in pedidos_adicionales)],
            "trabajos": [trabajo.pk for trabajo in trabajos], "referencia_excel": "Fila ficticia de Agenda General",
        }
        if planta:
            datos["planta"] = planta.pk
        self.post("coordinacion", "visita_pedido", datos, pedido.pk)
        return pedido.visitas.get()

    def resultado(self, visita, trabajo, estado, observacion=""):
        self.post("campo", "resultado_visita", {
            "estado": estado, "observacion": observacion, "referencia_sap": "NS-FICTICIA-CAMPO",
        }, visita.pk, trabajo.pk)
        trabajo.refresh_from_db()
        return visita.resultados.get(trabajo=trabajo)

    def facturacion(self, pedido, trabajo=None, modalidad="posterior", cobranza=False):
        datos = {"modalidad": modalidad, "correo_envio": "servicios@example.com"}
        if trabajo:
            datos["trabajos"] = [trabajo.pk]
        if cobranza:
            datos["cobranza_aplica"] = "on"
        self.post("comercial", "facturar_pedido", datos, pedido.pk)
        return pedido.solicitudes_facturacion.get()

    def factura_sap(self, solicitud, cobranza=False):
        datos = {
            "version": str(solicitud.movimientos.first().pk), "factura_sap": f"SAP-FICTICIA-{solicitud.pk}",
            "fecha_factura": self.hoy.isoformat(),
        }
        if cobranza:
            datos["cobranza_aplica"] = "on"
        self.post("admin", "actualizar_facturacion_trabajo", datos, solicitud.pk)
        solicitud.refresh_from_db()

    def test_abonado_multiequipo_abono_mensual_y_correctivo_adicional(self):
        cliente = self.crear_cliente("Abonado ficticio", Cliente.Tipo.ABONADO)
        planta = cliente.plantas.create(codigo="PL-81", nombre="Planta ficticia")
        generador = cliente.equipos.create(planta=planta, codigo="GEN-81", nombre="Generador ficticio")
        compresor = cliente.equipos.create(planta=planta, codigo="COM-81", nombre="Compresor ficticio")
        contrato = cliente.contratos_abono.create(
            referencia="AB-81", vigente_desde=self.hoy - timedelta(days=60), alcance="Visita preventiva",
            frecuencia="Mensual", valor=100000, moneda="ARS", cobertura_general=True,
        )
        ticket_abono = self.ticket(cliente, "Lavado incluido", planta, generador)
        lavado = self.accion(ticket_abono, "Lavar generador", Accion.Facturacion.ABONO)
        self.post("admin", "pedido_por_abono", {
            "contrato": contrato.pk, "cobertura_confirmada": "on", "alcance": "Lavado incluido", "equipos": [generador.pk],
        }, ticket_abono.pk)
        pedido_abono = ticket_abono.pedidos_servicio.get()
        self.post("admin", "seguimiento_pedido", {"estado": "enviado"}, pedido_abono.pk)

        ticket_correctivo = self.ticket(cliente, "Correctivo adicional", planta, compresor)
        correctivo = self.accion(ticket_correctivo, "Revisar vibración")
        adicional = self.pedido(self.cotizar(ticket_correctivo))
        visita = self.visita(pedido_abono, [lavado, correctivo], [adicional], planta)
        self.resultado(visita, lavado, "realizado")
        self.resultado(visita, correctivo, "parcial", "Queda medir la vibración con carga.")

        self.post("admin", "facturacion_abono_mes", {
            "estado": "facturada", "importe": "100000", "moneda": "ARS", "factura_sap": "SAP-MENSUAL-81",
            "fecha_factura": self.hoy.isoformat(),
        }, self.hoy.strftime("%Y-%m"), cliente.pk)
        cubierta = self.facturacion(pedido_abono, lavado, modalidad="abono")
        self.assertEqual(cubierta.estado, SolicitudFacturacionTrabajo.Estado.CUBIERTA)
        self.assertFalse(cubierta.factura_sap)
        self.assertTrue(lavado.realizada_el)
        self.assertIsNone(correctivo.realizada_el)
        ficha = self.sesiones["admin"].get(reverse("cliente", args=[cliente.pk]))
        for texto in ("Generador ficticio", "Compresor ficticio", "SAP-MENSUAL-81", "Queda medir la vibración"):
            self.assertContains(ficha, texto)

    def test_tercero_desde_analisis_hasta_cierre_con_permisos(self):
        cliente = self.crear_cliente("Tercero ficticio", Cliente.Tipo.TERCERO)
        ticket = self.ticket(cliente, "Servicio posterior")
        trabajo = self.accion(ticket, "Cambiar correas")
        self.post("tecnica", "nueva_solicitud_cotizacion", {
            "memoria": "Reemplazo de correas", "cantidad_tecnicos": "2", "horas_por_tecnico": "2",
            "repuestos-TOTAL_FORMS": "1", "repuestos-INITIAL_FORMS": "0",
            "repuestos-0-descripcion": "Correa ficticia", "repuestos-0-cantidad": "2",
        }, ticket.pk)
        tecnica = ticket.solicitudes_cotizacion.get()
        repuesto = tecnica.repuestos.get()
        self.post("comercial", "precio_repuesto", {
            "codigo": "COR-FICTICIA", "descripcion": repuesto.descripcion,
            "destinatario": "Compras", "solicitada_el": self.hoy.isoformat(),
        }, repuesto.pk)
        precio = repuesto.solicitudes_precio.get()
        self.post("comercial", "responder_solicitud_precio", {
            "recibida_el": self.hoy.isoformat(), "fuente": "Proveedor ficticio", "precio": "1000", "moneda": "ARS",
        }, precio.pk)
        self.post("admin", "revisar_solicitud_cotizacion", {"decision": "lista"}, tecnica.pk)
        pedido = self.pedido(self.cotizar(ticket, desde=tecnica))
        visita = self.visita(pedido, [trabajo])
        ajeno = reverse("resultado_visita", args=[visita.pk, trabajo.pk])
        respuesta = self.sesiones["otro_campo"].post(ajeno, {"estado": "realizado"})
        self.assertEqual(respuesta.status_code, 404)
        self.resultado(visita, trabajo, "realizado")
        self.resultado(visita, trabajo, "pendiente", "Envío repetido")
        self.assertEqual(visita.resultados.count(), 1)
        self.assertEqual(visita.resultados.get().estado, "realizado")
        solicitud = self.facturacion(pedido, trabajo)
        self.factura_sap(solicitud)
        self.post("admin", "llamada_sap_facturacion", {
            "referencia": "NS-FICTICIA-82", "circuito": "puntual", "facturaciones": [solicitud.pk], "visita": visita.pk,
        }, solicitud.pk)
        llamada = ticket.llamadas_sap.get()
        cierre = reverse("cerrar_llamada_sap", args=[llamada.pk])
        self.assertEqual(self.sesiones["comercial"].post(cierre).status_code, 403)
        self.post("admin", "cerrar_llamada_sap", {"fecha": self.hoy.isoformat(), "confirmado": "on"}, llamada.pk)
        self.assertContains(self.sesiones["admin"].get(reverse("llamada_sap", args=[llamada.pk])), "Cerrada en SAP")

    def test_venta_de_repuestos_sin_visita(self):
        cliente = self.crear_cliente("Repuestos ficticios", Cliente.Tipo.TERCERO)
        ticket = self.ticket(cliente, "Venta de filtro")
        pedido = self.pedido(self.cotizar(ticket), tipo="repuestos", modalidad_entrega="envio")
        self.post("admin", "seguimiento_pedido", {
            "estado": "entregado", "referencia": "Remito ficticio confirmado por Logística",
        }, pedido.pk)
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, PedidoServicio.Estado.ENTREGADO)
        self.assertFalse(pedido.visitas.exists())
        self.assertIsNone(pedido.fecha_agendada)
        solicitud = self.facturacion(pedido)
        self.factura_sap(solicitud)
        self.assertContains(self.sesiones["admin"].get(reverse("pedido_servicio", args=[pedido.pk])), "Remito ficticio")

    def test_facturacion_y_cobro_previos_con_ejecucion_posterior(self):
        cliente = self.crear_cliente("Servicio previo ficticio", Cliente.Tipo.TERCERO)
        ticket = self.ticket(cliente, "Servicio con facturación previa")
        trabajo = self.accion(ticket, "Ajustar generador")
        pedido = self.pedido(self.cotizar(ticket))
        solicitud = self.facturacion(pedido, trabajo, modalidad="previa", cobranza=True)
        self.factura_sap(solicitud, cobranza=True)
        self.assertEqual(solicitud.estado_cobranza, "Pendiente de cobro")
        self.post("admin", "actualizar_facturacion_trabajo", {
            "version": str(solicitud.movimientos.first().pk), "factura_sap": solicitud.factura_sap,
            "fecha_factura": self.hoy.isoformat(), "cobranza_aplica": "on",
            "referencia_cobro": "COBRO-FICTICIO-84", "fecha_cobro": self.hoy.isoformat(),
        }, solicitud.pk)
        trabajo.refresh_from_db()
        self.assertIsNone(trabajo.realizada_el)
        visita = self.visita(pedido, [trabajo])
        self.resultado(visita, trabajo, "realizado")
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudFacturacionTrabajo.Estado.FACTURADA)
        self.assertEqual(solicitud.estado_cobranza, "Cobrada")
        self.assertTrue(trabajo.realizada_el)
