from datetime import date, timedelta
from decimal import Decimal
from secrets import token_urlsafe

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Accion, AlertaCampo, Cliente, ContratoAbono, Cotizacion, Equipo, Planta, RegistroMantenimiento, Ticket
from .models import RespuestaPrecio, SolicitudCotizacion, SolicitudPrecio
from .models import FacturacionMensualAbono, PedidoServicio, Visita
from .models import ResultadoTrabajoVisita
from .permisos import ROLES_OFICINA, Rol


class PilotoTest(TestCase):
    def setUp(self):
        self.clave = token_urlsafe(18)
        self.oficina = User.objects.create_user("oficina.prueba", first_name="Inés Prueba", password=self.clave)
        self.oficina.groups.add(Group.objects.create(name="Oficina"))
        self.campo = User.objects.create_user("campo.prueba", first_name="Bruno Prueba", password=self.clave)
        self.otro = User.objects.create_user("otro.prueba", password=self.clave)
        Group.objects.get(name=Rol.CAMPO).user_set.add(self.campo, self.otro)

    def ingresar(self, usuario):
        self.client.post(reverse("salir"))
        respuesta = self.client.post(reverse("ingresar"), {
            "username": usuario.username, "password": self.clave,
        })
        self.assertRedirects(respuesta, reverse("inicio"))

    def crear_ticket(self):
        self.ingresar(self.oficina)
        cliente = Cliente.objects.create(codigo="AB-08", nombre="Cliente ficticio", tipo=Cliente.Tipo.ABONADO)
        equipo = Equipo.objects.create(cliente=cliente, codigo="GE-08", nombre="Generador GE-08")
        respuesta = self.client.post(reverse("nuevo"), {
            "asunto": "Lavado y vibración", "cliente_ficha": cliente.pk,
            "equipo_ficha": equipo.pk, "origen": "Visita",
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
        for consulta in (f"T-{ticket.pk}", ticket.asunto, ticket.cliente_nombre, ticket.equipo_nombre):
            self.assertContains(self.client.get(reverse("tickets"), {"q": consulta}), ticket.asunto)
        self.assertContains(self.client.get(reverse("tickets"), {"responsable": self.oficina.pk}), ticket.asunto)
        self.assertNotContains(self.client.get(reverse("tickets"), {"responsable": self.campo.pk}), ticket.asunto)
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


class CatalogoTest(TestCase):
    def setUp(self):
        self.oficina = User.objects.create_user("oficina.catalogo")
        self.oficina.groups.add(Group.objects.create(name="Oficina"))
        self.campo = User.objects.create_user("campo.catalogo")
        self.campo.groups.add(Group.objects.get(name=Rol.CAMPO))
        self.client.force_login(self.oficina)
        self.abonado = Cliente.objects.create(codigo="AB-01", nombre="Horizonte ficticio", tipo=Cliente.Tipo.ABONADO)
        self.tercero = Cliente.objects.create(codigo="TE-01", nombre="Taller ficticio", tipo=Cliente.Tipo.TERCERO)
        self.planta = Planta.objects.create(cliente=self.abonado, codigo="P1", nombre="Planta Norte")
        self.otra_planta = Planta.objects.create(cliente=self.abonado, codigo="P2", nombre="Planta Sur")
        self.equipo = Equipo.objects.create(
            cliente=self.abonado, planta=self.planta, codigo="GE-01", nombre="Generador", numero_serie="SERIE-123",
        )

    def test_listados_separados_y_fichas(self):
        abonados = self.client.get(reverse("abonados"), {"q": "AB-01"})
        self.assertContains(abonados, self.abonado.nombre)
        self.assertNotContains(abonados, self.tercero.nombre)
        self.assertContains(self.client.get(reverse("terceros")), self.tercero.nombre)
        clientes = self.client.get(reverse("cliente", args=[self.abonado.pk]))
        self.assertContains(clientes, self.planta.nombre)
        self.assertContains(clientes, self.otra_planta.nombre)
        self.assertContains(clientes, reverse("equipo", args=[self.equipo.pk]))
        self.assertContains(self.client.get(reverse("equipos"), {"q": "SERIE-123"}), self.equipo.nombre)
        self.assertContains(self.client.get(reverse("planta", args=[self.planta.pk])), self.equipo.nombre)

    def test_menu_de_oficina_y_ticket_desde_equipo(self):
        menu = self.client.get(reverse("inicio"))
        self.assertContains(menu, "Menú de Oficina")
        for vista in ("tickets", "clientes", "equipos"):
            self.assertContains(menu, f'href="{reverse(vista)}"')
        clientes = self.client.get(reverse("clientes"), {"q": self.tercero.codigo})
        self.assertContains(clientes, self.tercero.nombre)
        self.assertNotContains(clientes, self.abonado.nombre)
        self.assertContains(clientes, reverse("abonados"))
        self.assertContains(clientes, reverse("terceros"))
        ficha = self.client.get(reverse("equipo", args=[self.equipo.pk]))
        self.assertContains(ficha, reverse("cliente", args=[self.abonado.pk]))
        self.assertContains(ficha, reverse("planta", args=[self.planta.pk]))
        valores = {
            "cliente_ficha": str(self.abonado.pk), "equipo_ficha": str(self.equipo.pk),
            "planta_ficha": str(self.planta.pk),
        }
        nuevo = reverse("nuevo")
        formulario = self.client.get(nuevo, valores).context["form"]
        self.assertEqual(formulario.initial, valores)
        respuesta = self.client.post(nuevo, {"asunto": "Servicio desde equipo", **valores, "tipo": "tercero"})
        ticket = Ticket.objects.get()
        detalle = reverse("ticket", args=[ticket.pk])
        self.assertRedirects(respuesta, detalle)
        self.assertContains(self.client.get(detalle), "Abonado")
        self.assertContains(self.client.get(reverse("cliente", args=[self.abonado.pk])), ticket.asunto)

        self.client.force_login(self.campo)
        self.assertNotContains(self.client.get(reverse("inicio")), "Menú de Oficina")
        self.assertEqual(self.client.get(reverse("clientes")).status_code, 403)
        self.assertEqual(self.client.get(reverse("tickets")).status_code, 403)

    def test_altas_desde_el_catalogo(self):
        respuesta = self.client.post(reverse("nuevo_cliente"), {
            "codigo": "AB-02", "nombre": "Otra empresa ficticia", "tipo": Cliente.Tipo.ABONADO,
        })
        cliente = Cliente.objects.get(codigo="AB-02")
        self.assertRedirects(respuesta, reverse("cliente", args=[cliente.pk]))
        respuesta = self.client.post(reverse("nueva_planta"), {
            "cliente": cliente.pk, "codigo": "P1", "nombre": "Planta Centro",
        })
        planta = cliente.plantas.get()
        self.assertRedirects(respuesta, reverse("planta", args=[planta.pk]))
        respuesta = self.client.post(reverse("nuevo_equipo"), {
            "cliente": cliente.pk, "planta": planta.pk, "codigo": "GE-01", "nombre": "Generador auxiliar",
        })
        equipo = cliente.equipos.get()
        self.assertEqual(equipo.planta, planta)
        self.assertRedirects(respuesta, reverse("equipo", args=[equipo.pk]))

    def test_vincular_un_ticket_anterior_conserva_datos_e_historial(self):
        ticket = Ticket.objects.create(
            asunto="Reparación anterior", cliente="Cliente escrito a mano", planta="Sede anterior",
            equipo="Generador anterior", creado_por=self.oficina,
        )
        accion = ticket.acciones.create(
            titulo="Inspección", responsable=self.campo, estado=Accion.Estado.EN_CURSO,
        )
        accion.cambios.create(autor=self.campo, estado=Accion.Estado.EN_CURSO)
        detalle = reverse("ticket", args=[ticket.pk])
        self.assertContains(self.client.get(detalle), "Cliente escrito a mano")
        respuesta = self.client.post(reverse("vincular_ticket", args=[ticket.pk]), {
            "cliente_ficha": self.abonado.pk, "equipo_ficha": self.equipo.pk,
        })
        self.assertRedirects(respuesta, detalle)
        ticket.refresh_from_db()
        self.assertEqual(ticket.cliente, "Cliente escrito a mano")
        self.assertEqual(ticket.planta, "Sede anterior")
        self.assertEqual(ticket.equipo, "Generador anterior")
        self.assertEqual(ticket.cliente_ficha, self.abonado)
        self.assertEqual(ticket.equipo_ficha, self.equipo)
        self.assertEqual(ticket.planta_ficha, self.planta)
        self.assertEqual(accion.cambios.count(), 1)
        for ficha, registro in (("cliente", self.abonado), ("planta", self.planta), ("equipo", self.equipo)):
            self.assertContains(self.client.get(reverse(ficha, args=[registro.pk])), ticket.asunto)

    def test_rechaza_relaciones_incompatibles(self):
        respuesta = self.client.post(reverse("nuevo_equipo"), {
            "cliente": self.tercero.pk, "planta": self.planta.pk, "codigo": "INV", "nombre": "Equipo inválido",
        })
        self.assertContains(respuesta, "La planta debe pertenecer al cliente seleccionado.")
        self.assertFalse(Equipo.objects.filter(codigo="INV").exists())
        for cliente, planta, mensaje in (
            (self.tercero, self.planta, "El equipo debe pertenecer al cliente seleccionado."),
            (self.abonado, self.otra_planta, "El equipo está registrado en otra planta."),
        ):
            respuesta = self.client.post(reverse("nuevo"), {
                "asunto": "Vínculo inválido", "cliente_ficha": cliente.pk,
                "planta_ficha": planta.pk, "equipo_ficha": self.equipo.pk,
            })
            self.assertContains(respuesta, mensaje)
        self.assertFalse(Ticket.objects.exists())

    def test_campo_no_puede_acceder_a_las_fichas(self):
        self.client.force_login(self.campo)
        self.assertNotContains(self.client.get(reverse("inicio")), reverse("abonados"))
        self.assertEqual(self.client.get(reverse("equipo", args=[self.equipo.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("cliente", args=[self.abonado.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("abonados")).status_code, 403)


    def test_contacto_por_planta_y_edicion_acotada_al_cliente(self):
        alta = reverse("nuevo_contacto", args=[self.abonado.pk])
        datos = {"nombre": "Elena Ejemplo", "correo": "elena@example.com", "planta": self.planta.pk}
        respuesta = self.client.post(alta, datos)
        self.assertRedirects(respuesta, reverse("cliente", args=[self.abonado.pk]))
        contacto = self.abonado.contactos.get()
        self.assertEqual(contacto.planta, self.planta)

        ajena = Planta.objects.create(cliente=self.tercero, codigo="OTRA", nombre="Otra planta ficticia")
        edicion = reverse("editar_contacto", args=[self.abonado.pk, contacto.pk])
        respuesta = self.client.post(edicion, {**datos, "planta": ajena.pk})
        self.assertTrue(respuesta.context["form"].has_error("planta", "invalid_choice"))
        self.assertEqual(
            self.client.get(reverse("editar_contacto", args=[self.tercero.pk, contacto.pk])).status_code, 404,
        )
        respuesta = self.client.post(edicion, {**datos, "telefono": "555-0101"})
        self.assertEqual(respuesta.status_code, 302)
        ficha = self.client.get(reverse("cliente", args=[self.abonado.pk]))
        self.assertContains(ficha, "elena@example.com")
        self.assertContains(ficha, "555-0101")

    def test_documentos_por_cliente_y_permisos_de_lectura(self):
        alta = reverse("nuevo_documento", args=[self.abonado.pk])
        datos = {"tipo": "Llamada SAP", "referencia": "NS-123", "enlace": "https://example.com/ns-123"}
        respuesta = self.client.post(alta, datos)
        self.assertRedirects(respuesta, reverse("cliente", args=[self.abonado.pk]))
        self.assertContains(self.client.post(alta, datos), "Ya existe un documento")
        respuesta = self.client.post(alta, {**datos, "referencia": "NS-124", "enlace": "ftp://example.com/archivo"})
        self.assertTrue(respuesta.context["form"].has_error("enlace", "invalid"))
        self.assertEqual(self.abonado.documentos.count(), 1)
        comercial = User.objects.create_user("comercial.ficha")
        comercial.groups.add(Group.objects.create(name=Rol.COMERCIAL))
        self.client.force_login(comercial)
        self.assertContains(self.client.get(reverse("cliente", args=[self.abonado.pk])), datos["enlace"])
        self.assertNotContains(self.client.get(reverse("cliente", args=[self.tercero.pk])), "NS-123")
        self.assertEqual(self.client.post(alta, datos).status_code, 403)
        self.assertEqual(self.client.get(reverse("nuevo_contacto", args=[self.abonado.pk])).status_code, 403)

    def test_ficha_muestra_pendientes_y_completados_de_sus_tickets(self):
        ticket = Ticket.objects.create(asunto="Servicio local", cliente_ficha=self.abonado, creado_por=self.oficina)
        pendiente = ticket.acciones.create(
            titulo="Pendiente de revisión", responsable=self.campo, estado=Accion.Estado.EN_ESPERA,
            motivo_espera="Respuesta de Compras",
        )
        ticket.acciones.create(
            titulo="Lavado realizado", responsable=self.campo, estado=Accion.Estado.REALIZADA,
            realizada_el=timezone.now(), realizada_por=self.campo,
        )
        ajeno = Ticket.objects.create(asunto="Otro servicio", cliente_ficha=self.tercero, creado_por=self.oficina)
        ajeno.acciones.create(titulo="Trabajo de otro cliente", responsable=self.campo)

        ficha = self.client.get(reverse("cliente", args=[self.abonado.pk]))
        self.assertContains(ficha, "Pendientes: 1")
        self.assertContains(ficha, "Respuesta de Compras")
        self.assertContains(ficha, "Lavado realizado")
        self.assertNotContains(ficha, "Trabajo de otro cliente")
        detalle = reverse("ticket", args=[ticket.pk])
        self.assertContains(ficha, f"{detalle}#accion-{pendiente.pk}")
        self.assertContains(self.client.get(detalle), f'id="accion-{pendiente.pk}"')


class PermisosPorRolTest(TestCase):
    def setUp(self):
        self.comercial = User.objects.create_user("comercial.prueba")
        self.comercial.groups.add(Group.objects.create(name=Rol.COMERCIAL))
        campo = Group.objects.get(name=Rol.CAMPO)
        self.tecnico = User.objects.create_user("tecnico.prueba")
        self.otro = User.objects.create_user("otro.tecnico")
        campo.user_set.add(self.tecnico, self.otro)
        self.cliente = Cliente.objects.create(codigo="TE-10", nombre="Cliente de prueba", tipo=Cliente.Tipo.TERCERO)
        self.ticket = Ticket.objects.create(asunto="Generador ficticio", cliente_ficha=self.cliente, creado_por=self.comercial)
        self.accion = self.ticket.acciones.create(titulo="Inspección asignada", responsable=self.tecnico)

    def test_todos_los_roles_de_oficina_pueden_crear_tickets(self):
        for rol in sorted(ROLES_OFICINA):
            with self.subTest(rol=rol):
                self.comercial.groups.set([Group.objects.get_or_create(name=rol)[0]])
                self.client.force_login(self.comercial)
                self.assertContains(self.client.get(reverse("tickets")), self.ticket.asunto)
                respuesta = self.client.post(reverse("nuevo"), {
                    "asunto": f"Ticket de {rol}", "cliente_ficha": self.cliente.pk,
                })
                self.assertEqual(respuesta.status_code, 302)
                self.assertTrue(Ticket.objects.filter(asunto=f"Ticket de {rol}").exists())

    def test_comercial_lee_catalogo_y_administracion_puede_dar_alta(self):
        self.client.force_login(self.comercial)
        self.assertContains(self.client.get(reverse("terceros")), self.cliente.nombre)
        self.assertNotContains(self.client.get(reverse("terceros")), "Nuevo cliente")
        self.assertEqual(self.client.get(reverse("nuevo_cliente")).status_code, 403)
        self.assertEqual(self.client.post(reverse("nuevo_equipo"), {"nombre": "Equipo ficticio"}).status_code, 403)
        self.comercial.groups.set([Group.objects.create(name=Rol.ADMINISTRACION)])
        self.assertContains(self.client.get(reverse("terceros")), "Nuevo cliente")
        self.assertContains(self.client.get(reverse("nuevo_cliente")), "Guardar ficha")

    def test_campo_reporta_su_alerta_y_oficina_puede_consultarla(self):
        self.client.force_login(self.tecnico)
        self.assertContains(self.client.get(reverse("inicio")), "Reportar alerta")
        respuesta = self.client.post(reverse("nueva_alerta"), {
            "accion": self.accion.pk, "detalle": "Vibración de prueba", "autor": self.otro.pk,
        })
        self.assertRedirects(respuesta, reverse("alertas"))
        registro = AlertaCampo.objects.get()
        self.assertEqual(registro.autor, self.tecnico)
        self.assertEqual(registro.accion, self.accion)
        self.assertIsNotNone(registro.creada_el)
        self.assertContains(self.client.get(reverse("alertas")), registro.detalle)

        self.client.force_login(self.otro)
        self.assertNotContains(self.client.get(reverse("alertas")), registro.detalle)
        respuesta = self.client.post(reverse("nueva_alerta"), {"accion": self.accion.pk, "detalle": "Otra alerta"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["form"].has_error("accion", "invalid_choice"))
        self.assertEqual(AlertaCampo.objects.count(), 1)

        self.client.force_login(self.comercial)
        respuesta = self.client.get(reverse("alertas"))
        self.assertContains(respuesta, registro.detalle)
        self.assertContains(respuesta, reverse("ticket", args=[self.ticket.pk]))
        self.assertEqual(self.client.post(reverse("nueva_alerta"), {"detalle": "Otra alerta"}).status_code, 403)

    def test_cuenta_sin_funcion_no_puede_usar_servicios(self):
        sin_rol = User.objects.create_user("sin.funcion")
        self.client.force_login(sin_rol)
        for vista in ("inicio", "abonados", "nueva_alerta"):
            self.assertEqual(self.client.get(reverse(vista)).status_code, 403)


class ContratosAbonoTest(TestCase):
    def setUp(self):
        self.administracion = User.objects.create_user("administracion.abonos")
        self.administracion.groups.add(Group.objects.create(name=Rol.ADMINISTRACION))
        self.client.force_login(self.administracion)
        self.abonado = Cliente.objects.create(codigo="AB-01", nombre="Abonado ficticio", tipo=Cliente.Tipo.ABONADO)
        self.tercero = Cliente.objects.create(codigo="TE-01", nombre="Tercero ficticio", tipo=Cliente.Tipo.TERCERO)
        self.planta = self.abonado.plantas.create(codigo="P1", nombre="Planta Norte")
        self.equipo = self.abonado.equipos.create(planta=self.planta, codigo="GE", nombre="Generador")
        self.alta = reverse("nuevo_contrato_abono", args=[self.abonado.pk])
        self.datos = {
            "referencia": "AB-100", "vigente_desde": "2020-01-01", "alcance": "Visita preventiva",
            "frecuencia": "Mensual", "plantas": [self.planta.pk], "equipos": [self.equipo.pk],
            "valor": "13500.50", "moneda": "ars", "requiere_oc": "on", "requiere_hes": "on",
            "portal": "Portal ficticio", "requisitos_administrativos": "Adjuntar el informe de visita.",
        }

    def test_registra_cobertura_y_conserva_periodos_anteriores(self):
        fin = "2020-12-31"
        respuesta = self.client.post(self.alta, {**self.datos, "vigente_hasta": fin})
        anterior = self.abonado.contratos_abono.get()
        self.assertRedirects(respuesta, reverse("contrato_abono", args=[self.abonado.pk, anterior.pk]))
        self.assertEqual(anterior.estado_vigencia, "Vencido")
        respuesta = self.client.post(self.alta, {**self.datos, "vigente_desde": "2021-01-01"})
        contrato = self.abonado.contratos_abono.first()
        detalle = reverse("contrato_abono", args=[self.abonado.pk, contrato.pk])
        self.assertRedirects(respuesta, detalle)
        self.assertEqual(contrato.estado_vigencia, "Vigente")
        self.assertEqual(contrato.valor, Decimal("13500.50"))
        self.assertEqual(contrato.moneda, "ARS")
        self.assertTrue(contrato.requiere_hes and contrato.requiere_oc)
        self.assertEqual(list(contrato.plantas.all()), [self.planta])
        self.assertEqual(list(contrato.equipos.all()), [self.equipo])

        ficha = self.client.get(reverse("cliente", args=[self.abonado.pk]))
        self.assertContains(ficha, detalle)
        self.assertContains(ficha, "Vigente")
        self.assertContains(ficha, "Vencido")
        self.assertContains(self.client.get(detalle), "Portal ficticio")
        self.assertContains(self.client.get(detalle), reverse("equipo", args=[self.equipo.pk]))
        self.assertContains(self.client.post(self.alta, self.datos), "Ya existe un contrato")
        self.assertEqual(self.abonado.contratos_abono.count(), 2)

    def test_rechaza_fechas_invalidas_y_cobertura_ajena(self):
        planta_ajena = self.tercero.plantas.create(codigo="P1", nombre="Otra planta")
        equipo_ajeno = self.tercero.equipos.create(codigo="E1", nombre="Otro equipo")
        respuesta = self.client.post(self.alta, {
            **self.datos, "plantas": [planta_ajena.pk], "equipos": [equipo_ajeno.pk], "vigente_hasta": "2019-12-31",
        })
        for campo in ("plantas", "equipos"):
            self.assertTrue(respuesta.context["form"].has_error(campo, "invalid_choice"))
        self.assertContains(respuesta, "La fecha de fin debe ser igual o posterior")
        general = self.client.post(self.alta, {**self.datos, "cobertura_general": "on"})
        self.assertContains(general, "Elegí cobertura general o seleccioná")
        self.assertFalse(ContratoAbono.objects.exists())
        alta_tercero = reverse("nuevo_contrato_abono", args=[self.tercero.pk])
        self.assertEqual(self.client.post(alta_tercero, self.datos).status_code, 404)

    def test_edicion_y_lectura_segun_rol(self):
        self.client.post(self.alta, self.datos)
        contrato = self.abonado.contratos_abono.get()
        editar = reverse("editar_contrato_abono", args=[self.abonado.pk, contrato.pk])
        detalle = reverse("contrato_abono", args=[self.abonado.pk, contrato.pk])
        self.assertContains(self.client.get(editar), 'value="2020-01-01"')
        self.assertRedirects(
            self.client.post(editar, {**self.datos, "vigente_hasta": "2020-12-31"}), detalle,
        )
        contrato.refresh_from_db()
        self.assertEqual(contrato.vigente_hasta, date(2020, 12, 31))
        comercial = User.objects.create_user("comercial.abonos")
        comercial.groups.add(Group.objects.create(name=Rol.COMERCIAL))
        self.client.force_login(comercial)
        self.assertContains(self.client.get(detalle), "Qué cubre el abono")
        self.assertEqual(self.client.post(editar, self.datos).status_code, 403)
        campo = User.objects.create_user("campo.abonos")
        campo.groups.add(Group.objects.get(name=Rol.CAMPO))
        self.client.force_login(campo)
        self.assertEqual(self.client.get(detalle).status_code, 403)


class MantenimientoEquipoTest(TestCase):
    def setUp(self):
        self.tecnica = User.objects.create_user("tecnica.mantenimiento")
        self.tecnica.groups.add(Group.objects.create(name=Rol.RESPONSABLE_TECNICO))
        self.client.force_login(self.tecnica)
        self.cliente = Cliente.objects.create(codigo="AB-01", nombre="Abonado ficticio", tipo=Cliente.Tipo.ABONADO)
        self.planta = self.cliente.plantas.create(codigo="P1", nombre="Planta Norte")
        self.equipo = self.cliente.equipos.create(planta=self.planta, codigo="GE", nombre="Generador")
        self.alta = reverse("nuevo_mantenimiento", args=[self.equipo.pk])
        self.ficha = reverse("equipo", args=[self.equipo.pk])

    def test_distingue_ultima_visita_y_control_posterior(self):
        visita = timezone.localdate() - timedelta(days=3)
        control = timezone.localdate() - timedelta(days=1)
        respuesta = self.client.post(self.alta, {
            "fecha": visita.isoformat(), "visita_realizada": "on",
            "bateria": RegistroMantenimiento.EstadoControl.REALIZADO, "referencia_sap": "NS-FICTICIA-01",
        })
        self.assertRedirects(respuesta, self.ficha)
        respuesta = self.client.post(self.alta, {
            "fecha": control.isoformat(), "prueba_con_carga": RegistroMantenimiento.EstadoControl.PENDIENTE,
            "observaciones": "Coordinar con el electricista.",
        })
        self.assertRedirects(respuesta, self.ficha)
        ficha = self.client.get(self.ficha)
        self.assertEqual(ficha.context["ultima_visita"], visita)
        self.assertEqual([registro.fecha for registro in ficha.context["pagina"]], [control, visita])
        for texto in ("Prueba con carga", "Coordinar con el electricista.", "NS-FICTICIA-01", "tecnica.mantenimiento"):
            self.assertContains(ficha, texto)
        self.assertEqual(self.equipo.registros_mantenimiento.first().registrado_por, self.tecnica)

    def test_rechaza_registros_vacios_futuros_y_no_autorizados(self):
        hoy = timezone.localdate()
        respuesta = self.client.post(self.alta, {"fecha": hoy.isoformat()})
        self.assertContains(respuesta, "Indicá un control, una visita, una referencia SAP o una observación.")
        respuesta = self.client.post(self.alta, {"fecha": (hoy + timedelta(days=1)).isoformat(), "visita_realizada": "on"})
        self.assertContains(respuesta, "La fecha del registro no puede ser futura.")
        comercial = User.objects.create_user("comercial.mantenimiento")
        comercial.groups.add(Group.objects.create(name=Rol.COMERCIAL))
        self.client.force_login(comercial)
        self.assertContains(self.client.get(self.ficha), "Historial de mantenimiento")
        self.assertEqual(self.client.post(self.alta, {"fecha": hoy.isoformat(), "visita_realizada": "on"}).status_code, 403)
        self.assertFalse(RegistroMantenimiento.objects.exists())

    def test_actualiza_identificacion_sin_mover_el_equipo(self):
        editar = reverse("editar_equipo", args=[self.equipo.pk])
        self.assertEqual(self.client.get(editar).status_code, 403)
        self.tecnica.groups.add(Group.objects.create(name=Rol.ADMINISTRACION))
        respuesta = self.client.post(editar, {
            "nombre": "Generador principal", "numero_serie": "SERIE-DEMO", "ubicacion": "Sala de máquinas",
            "planta": "", "codigo": "otro",
        })
        self.assertRedirects(respuesta, self.ficha)
        self.equipo.refresh_from_db()
        self.assertEqual(self.equipo.planta, self.planta)
        self.assertEqual(self.equipo.codigo, "GE")
        ficha = self.client.get(self.ficha)
        self.assertContains(ficha, "SERIE-DEMO")
        self.assertContains(ficha, "Sala de máquinas")


class SolicitudCotizacionTest(TestCase):
    def setUp(self):
        grupo = Group.objects.create(name=Rol.RESPONSABLE_TECNICO)
        self.tecnica = User.objects.create_user("tecnica.solicitud")
        self.otro = User.objects.create_user("otro.solicitud")
        grupo.user_set.add(self.tecnica, self.otro)
        self.revisora = User.objects.create_user("revisora.solicitud")
        self.revisora.groups.add(Group.objects.create(name=Rol.ADMINISTRACION))
        self.cliente = Cliente.objects.create(codigo="AB-99", nombre="Abonado ficticio", tipo=Cliente.Tipo.ABONADO)
        self.ajeno = Cliente.objects.create(codigo="TE-99", nombre="Tercero ficticio", tipo=Cliente.Tipo.TERCERO)
        self.equipo = self.cliente.equipos.create(codigo="G-99", nombre="Generador")
        self.ticket = Ticket.objects.create(asunto="Revisión para cotizar", cliente_ficha=self.cliente, creado_por=self.tecnica)
        self.alta = reverse("nueva_solicitud_cotizacion", args=[self.ticket.pk])
        self.datos = {
            "equipos": [self.equipo.pk], "memoria": "Revisar y reemplazar correas.", "cantidad_tecnicos": "2",
            "horas_por_tecnico": "3.50", "duracion_estimada": "4.00", "referencia_origen": "NS-FICTICIA-99",
            "repuestos-TOTAL_FORMS": "1", "repuestos-INITIAL_FORMS": "0",
            "repuestos-0-descripcion": "Correa ficticia", "repuestos-0-cantidad": "2", "repuestos-0-por_equipo": "on",
        }
        self.client.force_login(self.tecnica)

    def crear_solicitud(self):
        respuesta = self.client.post(self.alta, self.datos)
        solicitud = self.ticket.solicitudes_cotizacion.get()
        detalle = reverse("solicitud_cotizacion", args=[solicitud.pk])
        self.assertRedirects(respuesta, detalle)
        return solicitud, detalle

    def test_devolucion_correccion_y_lista_para_cotizar(self):
        estado = SolicitudCotizacion.Estado
        solicitud, detalle = self.crear_solicitud()
        self.assertEqual(solicitud.horas_totales, Decimal("7.00"))
        self.assertEqual(solicitud.duracion_estimada, Decimal("4.00"))
        repuesto = solicitud.repuestos.get()
        self.assertTrue(repuesto.por_equipo)
        revisar = reverse("revisar_solicitud_cotizacion", args=[solicitud.pk])
        self.client.force_login(self.revisora)
        self.assertContains(self.client.post(revisar, {"decision": estado.DEVUELTA}), "Indicá qué información falta")
        devolucion = {"decision": estado.DEVUELTA, "nota": "Indicar el código de la correa."}
        self.assertRedirects(self.client.post(revisar, devolucion), detalle)
        self.assertContains(self.client.post(revisar, devolucion), "La solicitud ya fue revisada.")
        reenviar = reverse("reenviar_solicitud_cotizacion", args=[solicitud.pk])
        self.client.force_login(self.tecnica)
        self.assertContains(self.client.get(reenviar), devolucion["nota"])
        correccion = {
            **self.datos, "repuestos-INITIAL_FORMS": "1",
            "repuestos-0-id": repuesto.pk, "repuestos-0-referencia": "REP-99",
        }
        self.assertRedirects(self.client.post(reenviar, correccion), detalle)
        repuesto.refresh_from_db()
        self.assertEqual(repuesto.referencia, "REP-99")
        self.client.force_login(self.revisora)
        self.assertRedirects(self.client.post(revisar, {"decision": estado.LISTA}), detalle)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, estado.LISTA)
        self.assertEqual(list(solicitud.cambios.order_by("pk").values_list("estado", flat=True)), [
            estado.ENVIADA, estado.DEVUELTA, estado.ENVIADA, estado.LISTA,
        ])

    def test_rechaza_equipo_ajeno_y_preserva_cliente_del_ticket(self):
        ajeno = self.ajeno.equipos.create(codigo="E-99", nombre="Equipo ajeno")
        respuesta = self.client.post(self.alta, {**self.datos, "equipos": [ajeno.pk]})
        self.assertTrue(respuesta.context["form"].has_error("equipos", "invalid_choice"))
        self.assertFalse(self.ticket.solicitudes_cotizacion.exists())
        self.crear_solicitud()
        respuesta = self.client.post(reverse("vincular_ticket", args=[self.ticket.pk]), {"cliente_ficha": self.ajeno.pk})
        self.assertContains(respuesta, "Conservá su cliente.")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.cliente_ficha, self.cliente)

    def test_alcance_de_acceso_por_rol_y_propiedad(self):
        solicitud, detalle = self.crear_solicitud()
        self.assertContains(self.client.get(reverse("solicitudes_cotizacion")), self.ticket.asunto)
        self.client.force_login(self.otro)
        self.assertNotContains(self.client.get(reverse("solicitudes_cotizacion")), self.ticket.asunto)
        self.assertEqual(self.client.get(detalle).status_code, 404)
        self.assertEqual(self.client.post(reverse("revisar_solicitud_cotizacion", args=[solicitud.pk])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("ticket", args=[self.ticket.pk])), detalle)
        self.client.force_login(self.revisora)
        self.assertContains(self.client.get(detalle), self.ticket.asunto)
        self.assertEqual(self.client.get(self.alta).status_code, 403)


class CotizacionTest(TestCase):
    def setUp(self):
        self.comercial = User.objects.create_user("comercial.cotizacion")
        self.comercial.groups.add(Group.objects.create(name=Rol.COMERCIAL))
        self.client.force_login(self.comercial)
        self.abonado = Cliente.objects.create(codigo="AB-04", nombre="Abonado ficticio", tipo=Cliente.Tipo.ABONADO)
        self.tercero = Cliente.objects.create(codigo="TE-04", nombre="Tercero ficticio", tipo=Cliente.Tipo.TERCERO)
        self.ticket = Ticket.objects.create(asunto="Cambio de correas", cliente_ficha=self.tercero, creado_por=self.comercial)
        self.nueva = reverse("nueva_cotizacion", args=[self.ticket.pk])

    def test_directa_envio_aprobacion_y_oc_posterior(self):
        datos = {"alcance": "Cambio de dos correas", "referencia": "PRES-44"}
        respuesta = self.client.post(self.nueva, datos)
        cotizacion = self.ticket.cotizaciones.get()
        detalle = reverse("cotizacion", args=[cotizacion.pk])
        enviar = reverse("enviar_cotizacion", args=[cotizacion.pk])
        responder = reverse("respuesta_cotizacion", args=[cotizacion.pk])
        editar = reverse("editar_cotizacion", args=[cotizacion.pk])
        self.assertRedirects(respuesta, detalle)
        self.assertContains(self.client.post(enviar), "Completá el importe y la moneda")
        self.assertRedirects(self.client.post(editar, {**datos, "importe": "15000", "moneda": "ars"}), detalle)
        self.assertRedirects(self.client.post(enviar), detalle)
        self.assertEqual(self.client.post(enviar).status_code, 404)
        self.assertContains(self.client.post(responder, {"decision": "aprobada"}), "Registrá la confirmación")
        correo = {"confirmacion_correo": "Correo del cliente"}
        self.assertRedirects(self.client.post(responder, {"decision": "aprobada", **correo}), detalle)
        respaldo = {**correo, "orden_compra": "OC-45"}
        self.assertRedirects(self.client.post(responder, respaldo), detalle)
        self.assertRedirects(self.client.post(responder, respaldo), detalle)
        cotizacion.refresh_from_db()
        self.assertEqual(cotizacion.estado, Cotizacion.Estado.APROBADA)
        self.assertEqual(cotizacion.confirmacion_correo, "Correo del cliente")
        self.assertEqual(cotizacion.orden_compra, "OC-45")
        self.assertEqual(cotizacion.cambios.count(), 4)
        self.assertContains(self.client.get(reverse("cotizaciones_terceros"), {"q": "PRES-44"}), "Aprobada")
        self.assertContains(self.client.get(reverse("ticket", args=[self.ticket.pk])), detalle)

    def test_solicitud_lista_y_cotizacion_de_abonado_en_su_ficha(self):
        ticket = Ticket.objects.create(asunto="Revisión de abonado", cliente_ficha=self.abonado, creado_por=self.comercial)
        solicitud = SolicitudCotizacion.objects.create(
            ticket=ticket, solicitante=self.comercial, memoria="Analizar el alcance.", cantidad_tecnicos=2, horas_por_tecnico=3,
        )
        origen = reverse("cotizar_solicitud", args=[solicitud.pk])
        self.assertEqual(self.client.get(origen).status_code, 404)
        solicitud.estado = SolicitudCotizacion.Estado.LISTA
        solicitud.save(update_fields=["estado"])
        self.assertContains(self.client.get(origen), solicitud.memoria)
        respuesta = self.client.post(origen, {"alcance": "Mano de obra y repuestos", "referencia": "AB-PRES-99"})
        cotizacion = solicitud.cotizaciones.get()
        self.assertRedirects(respuesta, reverse("cotizacion", args=[cotizacion.pk]))
        self.assertNotContains(self.client.get(reverse("cotizaciones_terceros")), "AB-PRES-99")
        self.assertContains(self.client.get(reverse("cliente", args=[self.abonado.pk])), "AB-PRES-99")

    def test_rechazo_y_permiso_por_enlace_directo(self):
        self.client.post(self.nueva, {"alcance": "Alcance ficticio", "importe": "100", "moneda": "USD"})
        cotizacion = self.ticket.cotizaciones.get()
        detalle = reverse("cotizacion", args=[cotizacion.pk])
        self.client.post(reverse("enviar_cotizacion", args=[cotizacion.pk]))
        respuesta = reverse("respuesta_cotizacion", args=[cotizacion.pk])
        self.assertContains(self.client.post(respuesta, {"decision": "rechazada"}), "Indicá la respuesta")
        self.assertRedirects(self.client.post(respuesta, {"decision": "rechazada", "nota": "Cliente desistió."}), detalle)
        self.assertContains(self.client.get(detalle), "Cliente desistió.")
        self.assertEqual(self.client.post(respuesta, {"decision": "aprobada", "orden_compra": "OC-90"}).status_code, 404)
        campo = User.objects.create_user("campo.cotizacion")
        campo.groups.add(Group.objects.get(name=Rol.CAMPO))
        self.client.force_login(campo)
        self.assertEqual(self.client.get(detalle).status_code, 403)


class SolicitudPrecioTest(TestCase):
    def setUp(self):
        self.comercial = User.objects.create_user("comercial.precios")
        self.comercial.groups.add(Group.objects.create(name=Rol.COMERCIAL))
        self.client.force_login(self.comercial)
        self.hoy = timezone.localdate()
        self.datos = {
            "codigo": "COR-91", "descripcion": "Correa estriada", "destinatario": "Compras",
            "solicitada_el": (self.hoy - timedelta(days=2)).isoformat(),
        }
        self.respuesta = {
            "recibida_el": (self.hoy - timedelta(days=1)).isoformat(), "fuente": "Proveedor ficticio",
            "precio": "1250.50", "moneda": "ars", "vigente_hasta": (self.hoy + timedelta(days=10)).isoformat(),
            "respuesta": "Precio confirmado por Compras.",
        }

    def test_bandeja_respuestas_y_actualizacion_sin_sobrescribir(self):
        nueva = reverse("nueva_solicitud_precio")
        vista = reverse("solicitudes_precio")
        self.client.post(nueva, self.datos)
        original = SolicitudPrecio.objects.get()
        enlace = reverse("solicitud_precio", args=[original.pk])
        self.assertContains(self.client.get(vista, {"q": "COR-91", "estado": "pendiente"}), enlace)
        self.assertContains(self.client.get(vista, {"q": "estriada"}), enlace)
        responder = reverse("responder_solicitud_precio", args=[original.pk])
        for _ in range(2):
            self.assertRedirects(self.client.post(responder, self.respuesta), enlace)
        self.assertEqual(original.respuestas.count(), 1)
        self.assertEqual(original.respuestas.get().moneda, "ARS")
        self.assertEqual(original.respuestas.get().precio, Decimal("1250.50"))
        self.assertContains(self.client.get(enlace), "Proveedor ficticio")
        self.assertNotContains(self.client.get(vista, {"estado": "pendiente"}), enlace)
        self.assertContains(self.client.get(vista, {"estado": "respondida"}), enlace)

        actualizar = reverse("actualizar_solicitud_precio", args=[original.pk])
        self.assertContains(self.client.get(actualizar), "Consultar precios anteriores")
        self.client.post(actualizar, {**self.datos, "solicitada_el": self.hoy.isoformat()})
        actualizacion = original.actualizaciones.get()
        self.client.post(reverse("responder_solicitud_precio", args=[actualizacion.pk]), {
            **self.respuesta, "recibida_el": self.hoy.isoformat(), "precio": "1500",
        })
        self.assertEqual(actualizacion.respuestas.get().precio, Decimal("1500"))
        self.assertEqual(original.respuestas.get().precio, Decimal("1250.50"))
        self.assertContains(self.client.get(enlace), reverse("solicitud_precio", args=[actualizacion.pk]))

    def test_valida_fechas_y_restringe_acceso(self):
        self.client.post(reverse("nueva_solicitud_precio"), self.datos)
        solicitud = SolicitudPrecio.objects.get()
        responder = reverse("responder_solicitud_precio", args=[solicitud.pk])
        fecha_anterior = (self.hoy - timedelta(days=3)).isoformat()
        respuesta = self.client.post(responder, {**self.respuesta, "recibida_el": fecha_anterior})
        self.assertContains(respuesta, "La respuesta no puede ser anterior")
        respuesta = self.client.post(responder, {**self.respuesta, "vigente_hasta": fecha_anterior})
        self.assertContains(respuesta, "La vigencia no puede terminar antes")
        self.assertFalse(RespuestaPrecio.objects.exists())
        campo = User.objects.create_user("campo.precios")
        campo.groups.add(Group.objects.get(name=Rol.CAMPO))
        self.client.force_login(campo)
        self.assertEqual(self.client.get(reverse("solicitudes_precio")).status_code, 403)
        self.assertEqual(self.client.post(responder, self.respuesta).status_code, 403)

    def test_vinculos_a_cotizacion_y_repuesto_sin_perder_historial(self):
        cliente = Cliente.objects.create(codigo="TE-91", nombre="Tercero ficticio", tipo=Cliente.Tipo.TERCERO)
        ticket = Ticket.objects.create(asunto="Trabajo ficticio", cliente_ficha=cliente, creado_por=self.comercial)
        cotizacion = ticket.cotizaciones.create(alcance="Verificar correas")
        self.client.post(reverse("precio_cotizacion", args=[cotizacion.pk]), self.datos)
        precio = cotizacion.solicitudes_precio.get()
        self.assertContains(self.client.get(reverse("cotizacion", args=[cotizacion.pk])), precio.descripcion)

        tecnica = ticket.solicitudes_cotizacion.create(
            solicitante=self.comercial, memoria="Revisar la correa", cantidad_tecnicos=1, horas_por_tecnico=1,
        )
        repuesto = tecnica.repuestos.create(descripcion="Correa estriada", referencia="COR-91", cantidad=1)
        alta = reverse("precio_repuesto", args=[repuesto.pk])
        self.assertContains(self.client.get(alta), "Consultar precios anteriores")
        self.client.post(alta, self.datos)
        solicitud = repuesto.solicitudes_precio.get()
        repuesto.delete()
        solicitud.refresh_from_db()
        self.assertIsNone(solicitud.repuesto_id)
        self.assertEqual(solicitud.codigo, "COR-91")


class PedidoServicioTest(TestCase):
    def setUp(self):
        self.administracion = User.objects.create_user("administracion.pedidos")
        self.administracion.groups.add(Group.objects.create(name=Rol.ADMINISTRACION))
        self.coordinacion = User.objects.create_user("coordinacion.pedidos")
        self.coordinacion.groups.add(Group.objects.create(name=Rol.COORDINACION))
        self.client.force_login(self.administracion)
        self.cliente = Cliente.objects.create(codigo="AB-51", nombre="Abonado ficticio", tipo=Cliente.Tipo.ABONADO)
        self.tercero = Cliente.objects.create(codigo="TE-51", nombre="Tercero ficticio", tipo=Cliente.Tipo.TERCERO)
        self.ticket = Ticket.objects.create(asunto="Servicio ficticio", cliente_ficha=self.cliente, creado_por=self.administracion)
        self.otro_ticket = Ticket.objects.create(asunto="Segundo trabajo", cliente_ficha=self.cliente, creado_por=self.administracion)
        self.cotizacion = self.ticket.cotizaciones.create(alcance="Revisar generador", estado=Cotizacion.Estado.APROBADA)
        self.otro_presupuesto = self.otro_ticket.cotizaciones.create(
            alcance="Cambio de correas", estado=Cotizacion.Estado.APROBADA,
        )
        self.equipo = self.cliente.equipos.create(codigo="EQ-51", nombre="Generador ficticio")
        self.alta = reverse("pedido_desde_cotizacion", args=[self.cotizacion.pk])
        self.datos = {
            "alcance": "Revisión y cambio de correas", "tipo": "servicio",
            "cotizaciones": [self.cotizacion.pk, self.otro_presupuesto.pk], "equipos": [self.equipo.pk],
        }

    def test_pedido_de_varias_cotizaciones_y_seguimiento_en_excel(self):
        respuesta = self.client.post(self.alta, self.datos)
        pedido = self.ticket.pedidos_servicio.get()
        detalle = reverse("pedido_servicio", args=[pedido.pk])
        seguir = reverse("seguimiento_pedido", args=[pedido.pk])
        self.assertRedirects(respuesta, detalle)
        self.assertEqual(set(pedido.cotizaciones.all()), {self.cotizacion, self.otro_presupuesto})
        self.assertContains(self.client.get(reverse("ticket", args=[self.otro_ticket.pk])), detalle)
        self.assertRedirects(self.client.post(seguir, {"estado": "enviado", "referencia": "Correo ficticio"}), detalle)
        self.client.force_login(self.coordinacion)
        self.assertRedirects(self.client.post(seguir, {"estado": "pendiente_agendar"}), detalle)
        self.assertContains(self.client.post(seguir, {"estado": "agendado"}), "Indicá la fecha registrada")
        self.assertRedirects(self.client.post(seguir, {
            "estado": "agendado", "fecha_agendada": "2026-12-15", "referencia": "Agenda General",
        }), detalle)
        pedido.refresh_from_db()
        self.assertEqual(pedido.fecha_agendada, date(2026, 12, 15))
        self.assertEqual(list(pedido.cambios.order_by("pk").values_list("estado", flat=True)), [
            "preparacion", "enviado", "pendiente_agendar", "agendado",
        ])
        self.assertContains(self.client.get(reverse("pedidos_servicio"), {"estado": "agendado"}), detalle)

    def test_cobertura_confirmada_y_rechazo_de_fuentes_ajenas(self):
        contrato = self.cliente.contratos_abono.create(
            referencia="AB-51", vigente_desde=date(2020, 1, 1), alcance="Servicio preventivo",
            frecuencia="Mensual", valor=100, moneda="ARS", cobertura_general=True,
        )
        alta = reverse("pedido_por_abono", args=[self.ticket.pk])
        formulario = {"contrato": contrato.pk, "alcance": "Visita de abono", "equipos": [self.equipo.pk]}
        self.assertTrue(self.client.post(alta, formulario).context["form"].has_error("cobertura_confirmada", "required"))
        self.client.post(alta, {**formulario, "cobertura_confirmada": "on", "tipo": "repuestos"})
        self.assertEqual(contrato.pedidos_servicio.get().tipo, PedidoServicio.Tipo.SERVICIO)
        ajeno = Ticket.objects.create(asunto="Servicio ajeno", cliente_ficha=self.tercero, creado_por=self.administracion)
        cotizacion_ajena = ajeno.cotizaciones.create(alcance="Otra oferta", estado=Cotizacion.Estado.APROBADA)
        equipo_ajeno = self.tercero.equipos.create(codigo="OTRO", nombre="Otro generador")
        respuesta = self.client.post(self.alta, {
            **self.datos, "cotizaciones": [cotizacion_ajena.pk], "equipos": [equipo_ajeno.pk],
        })
        self.assertTrue(respuesta.context["form"].has_error("cotizaciones", "invalid_choice"))
        self.assertTrue(respuesta.context["form"].has_error("equipos", "invalid_choice"))
        self.assertEqual(self.client.get(reverse("pedido_por_abono", args=[ajeno.pk])).status_code, 404)
        self.cotizacion.estado = Cotizacion.Estado.PREPARACION
        self.cotizacion.save(update_fields=["estado"])
        self.assertEqual(self.client.get(self.alta).status_code, 404)

    def test_venta_de_repuestos_registra_confirmacion_de_logistica(self):
        datos = {**self.datos, "tipo": "repuestos"}
        self.assertContains(self.client.post(self.alta, datos), "Indicá retiro en depósito o envío.")
        self.client.post(self.alta, {**datos, "modalidad_entrega": "retiro"})
        pedido = self.ticket.pedidos_servicio.get()
        detalle = reverse("pedido_servicio", args=[pedido.pk])
        seguir = reverse("seguimiento_pedido", args=[pedido.pk])
        self.assertContains(self.client.get(detalle), "Retiro en depósito")
        self.assertRedirects(self.client.post(seguir, {"estado": "enviado"}), detalle)
        self.assertContains(self.client.post(seguir, {"estado": "entregado"}), "confirmación o referencia informada")
        self.assertRedirects(self.client.post(seguir, {"estado": "entregado", "referencia": "Remito ficticio"}), detalle)
        self.assertContains(self.client.get(detalle), "Remito ficticio")
        pedido.refresh_from_db()
        self.assertIsNone(pedido.fecha_agendada)
        self.assertEqual(pedido.estado, PedidoServicio.Estado.ENTREGADO)
        campo = User.objects.create_user("campo.pedidos")
        campo.groups.add(Group.objects.get(name=Rol.CAMPO))
        self.client.force_login(campo)
        self.assertEqual(self.client.get(detalle).status_code, 403)


class AgendaOperativaTest(TestCase):
    def setUp(self):
        self.coordinacion = User.objects.create_user("coordinacion.agenda")
        self.coordinacion.groups.add(Group.objects.create(name=Rol.COORDINACION))
        self.client.force_login(self.coordinacion)
        campo = Group.objects.get(name=Rol.CAMPO)
        self.tecnico = User.objects.create_user("bruno.agenda")
        self.segundo = User.objects.create_user("vera.agenda")
        self.ajeno = User.objects.create_user("otro.agenda")
        campo.user_set.add(self.tecnico, self.segundo, self.ajeno)
        self.cliente = Cliente.objects.create(codigo="AB-52", nombre="Abonado ficticio", tipo=Cliente.Tipo.ABONADO)
        self.planta = self.cliente.plantas.create(codigo="P-1", nombre="Planta ficticia")
        self.ticket = Ticket.objects.create(
            asunto="Servicio ficticio", cliente_ficha=self.cliente, planta_ficha=self.planta, creado_por=self.coordinacion,
        )
        self.pedido = self.ticket.pedidos_servicio.create(alcance="Visita de ejemplo", estado=PedidoServicio.Estado.ENVIADO)
        self.trabajo = self.ticket.acciones.create(titulo="Revisar vibración", responsable=self.tecnico)
        self.otro_trabajo = self.ticket.acciones.create(titulo="Lavar generador", responsable=self.segundo)
        self.alta = reverse("visita_pedido", args=[self.pedido.pk])
        self.datos = {
            "planta": self.planta.pk, "fecha": "2026-12-15", "hora_desde": "09:00", "hora_hasta": "11:00",
            "referencia_excel": "DATOS, fila ficticia 15", "tecnicos": [self.tecnico.pk, self.segundo.pk],
            "pedidos": [self.pedido.pk], "trabajos": [self.trabajo.pk, self.otro_trabajo.pk],
        }

    def test_visita_con_varios_tecnicos_y_trabajos_y_filtro(self):
        respuesta = self.client.post(self.alta, self.datos)
        visita = Visita.objects.get()
        detalle = reverse("visita", args=[visita.pk])
        self.assertRedirects(respuesta, detalle)
        self.assertEqual(set(visita.tecnicos.all()), {self.tecnico, self.segundo})
        self.assertEqual(set(visita.trabajos.all()), {self.trabajo, self.otro_trabajo})
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, PedidoServicio.Estado.AGENDADO)
        for tecnico in (self.tecnico, self.segundo):
            agenda = self.client.get(reverse("agenda"), {"dia": self.datos["fecha"], "tecnico": tecnico.pk})
            self.assertContains(agenda, "Revisar vibración")
            self.assertContains(agenda, "Planta ficticia")
        agenda = self.client.get(reverse("agenda"), {"dia": self.datos["fecha"], "tecnico": self.ajeno.pk})
        self.assertNotContains(agenda, detalle)
        self.assertContains(self.client.get(reverse("pedido_servicio", args=[self.pedido.pk])), detalle)
        self.assertContains(self.client.get(reverse("cliente", args=[self.cliente.pk])), detalle)

    def test_reprogramacion_conserva_fecha_anterior_y_actualiza_pedido(self):
        self.client.post(self.alta, self.datos)
        visita = Visita.objects.get()
        editar = reverse("reprogramar_visita", args=[visita.pk])
        datos = {
            "fecha": "2026-12-17", "hora_desde": "10:00", "hora_hasta": "12:00",
            "referencia_excel": "DATOS, fila ficticia 17",
        }
        self.assertTrue(self.client.post(editar, datos).context["form"].has_error("motivo", "required"))
        motivo = "Reprogramada a pedido del cliente"
        self.assertRedirects(self.client.post(editar, {**datos, "motivo": motivo}), reverse("visita", args=[visita.pk]))
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.fecha_agendada, date(2026, 12, 17))
        movimientos = list(visita.movimientos.order_by("pk"))
        self.assertEqual([movimiento.fecha for movimiento in movimientos], [date(2026, 12, 15), date(2026, 12, 17)])
        self.assertEqual(movimientos[-1].motivo, motivo)
        self.assertContains(self.client.post(editar, {**datos, "motivo": motivo}), "Indicá una fecha u horario diferente.")
        self.assertEqual(visita.movimientos.count(), 2)

    def test_validaciones_y_permisos(self):
        cliente_ajeno = Cliente.objects.create(codigo="TE-52", nombre="Tercero ficticio", tipo=Cliente.Tipo.TERCERO)
        otro_ticket = Ticket.objects.create(asunto="Otro cliente", cliente_ficha=cliente_ajeno, creado_por=self.coordinacion)
        ajeno = otro_ticket.acciones.create(titulo="Trabajo ajeno", responsable=self.tecnico)
        respuesta = self.client.post(self.alta, {**self.datos, "hora_hasta": "08:00", "trabajos": [ajeno.pk]})
        self.assertTrue(respuesta.context["form"].has_error("trabajos", "invalid_choice"))
        self.assertContains(respuesta, "La hora de fin debe ser posterior")
        self.assertFalse(Visita.objects.exists())
        self.client.force_login(self.tecnico)
        self.assertEqual(self.client.get(reverse("agenda")).status_code, 403)
        self.assertEqual(self.client.post(self.alta, self.datos).status_code, 403)


class ServiciosTecnicosTest(TestCase):
    def setUp(self):
        self.oficina = User.objects.create_user("oficina.campo")
        self.oficina.groups.add(Group.objects.create(name=Rol.COORDINACION))
        campo = Group.objects.get(name=Rol.CAMPO)
        self.tecnico = User.objects.create_user("bruno.campo")
        self.otro = User.objects.create_user("vera.campo")
        self.ajeno = User.objects.create_user("ajeno.campo")
        campo.user_set.add(self.tecnico, self.otro, self.ajeno)
        self.cliente = Cliente.objects.create(codigo="AB-53", nombre="Abonado ficticio", tipo=Cliente.Tipo.ABONADO)
        ticket = Ticket.objects.create(asunto="Servicio ficticio", cliente_ficha=self.cliente, creado_por=self.oficina)
        self.trabajo = ticket.acciones.create(titulo="Lavado ficticio", responsable=self.tecnico)
        self.otro_trabajo = ticket.acciones.create(titulo="Revisión ficticia", responsable=self.otro)
        self.visita = self.crear_visita(date(2026, 11, 15))
        self.visita.trabajos.add(self.trabajo, self.otro_trabajo)
        self.detalle = reverse("servicio_visita", args=[self.visita.pk])
        self.alta = reverse("resultado_visita", args=[self.visita.pk, self.trabajo.pk])

    def crear_visita(self, fecha):
        visita = Visita.objects.create(cliente=self.cliente, fecha=fecha, hora_desde="09:00", hora_hasta="11:00")
        visita.tecnicos.add(self.tecnico, self.otro)
        return visita

    def test_registra_resultados_independientes_y_evitar_doble_envio(self):
        self.client.force_login(self.tecnico)
        self.assertContains(self.client.get(reverse("servicios_tecnicos")), self.detalle)
        self.assertContains(self.client.get(reverse("inicio")), f"{self.detalle}#trabajo-{self.trabajo.pk}")
        self.assertRedirects(
            self.client.post(reverse("realizar", args=[self.trabajo.pk])), reverse("servicios_tecnicos"),
        )
        datos = {"estado": "realizado", "referencia_sap": "LLAMADA-FICTICIA-53"}
        self.assertRedirects(self.client.post(self.alta, datos), self.detalle)
        self.assertRedirects(self.client.post(self.alta, {"estado": "pendiente"}), self.detalle)
        registro = ResultadoTrabajoVisita.objects.get()
        self.assertEqual(registro.autor, self.tecnico)
        self.assertEqual(registro.responsable, self.tecnico)
        self.assertEqual(registro.estado, ResultadoTrabajoVisita.Estado.REALIZADO)
        self.trabajo.refresh_from_db()
        self.otro_trabajo.refresh_from_db()
        self.assertEqual(self.trabajo.realizada_el, registro.registrado_el)
        self.assertEqual(self.trabajo.realizada_por, self.tecnico)
        self.assertIsNone(self.otro_trabajo.realizada_el)
        self.assertNotContains(self.client.get(self.detalle), "Revisión ficticia")

        self.client.force_login(self.oficina)
        resultado = self.client.get(self.detalle)
        for texto in ("Lavado ficticio", "Revisión ficticia", "LLAMADA-FICTICIA-53", "Pendiente de registrar resultado."):
            self.assertContains(resultado, texto)
        self.assertEqual(self.client.post(self.alta, datos).status_code, 403)
        reprogramar = reverse("reprogramar_visita", args=[self.visita.pk])
        self.assertEqual(self.client.get(reprogramar).status_code, 409)

    def test_parcial_y_pendiente_seguido_de_realizado_en_otra_visita(self):
        self.client.force_login(self.tecnico)
        self.assertContains(
            self.client.post(self.alta, {"estado": "parcial"}), "Indicá qué falta para poder continuar",
        )
        self.client.post(self.alta, {"estado": "parcial", "observacion": "Queda limpiar el interior."})
        self.trabajo.refresh_from_db()
        self.assertEqual(self.trabajo.estado, Accion.Estado.EN_ESPERA)
        self.assertEqual(self.trabajo.motivo_espera, "Queda limpiar el interior.")
        self.assertIsNone(self.trabajo.realizada_el)
        segunda = self.crear_visita(date(2026, 11, 16))
        segunda.trabajos.add(self.trabajo)
        self.client.post(reverse("resultado_visita", args=[segunda.pk, self.trabajo.pk]), {
            "estado": "pendiente", "observacion": "Falta acceso al equipo.",
        })
        tercera = self.crear_visita(date(2026, 11, 17))
        tercera.trabajos.add(self.trabajo)
        self.client.post(reverse("resultado_visita", args=[tercera.pk, self.trabajo.pk]), {"estado": "realizado"})
        self.assertEqual(
            list(self.trabajo.resultados_visita.order_by("pk").values_list("estado", flat=True)),
            ["parcial", "pendiente", "realizado"],
        )
        self.trabajo.refresh_from_db()
        self.assertEqual(self.trabajo.estado, Accion.Estado.REALIZADA)

    def test_acceso_directo_a_visita_o_trabajo_ajeno(self):
        self.client.force_login(self.ajeno)
        self.assertNotContains(self.client.get(reverse("servicios_tecnicos")), self.detalle)
        self.assertEqual(self.client.get(self.detalle).status_code, 404)
        self.assertEqual(self.client.post(self.alta, {"estado": "realizado"}).status_code, 404)
        self.client.force_login(self.otro)
        self.assertEqual(self.client.post(self.alta, {"estado": "realizado"}).status_code, 404)
        self.assertFalse(ResultadoTrabajoVisita.objects.exists())


class FacturacionMensualAbonoTest(TestCase):
    def setUp(self):
        self.oficina = User.objects.create_user("oficina.facturacion")
        self.oficina.groups.add(Group.objects.create(name=Rol.ADMINISTRACION))
        self.client.force_login(self.oficina)
        self.cliente = Cliente.objects.create(codigo="AB-61", nombre="Abonado ficticio", tipo=Cliente.Tipo.ABONADO)
        self.tercero = Cliente.objects.create(codigo="TE-61", nombre="Tercero ficticio", tipo=Cliente.Tipo.TERCERO)
        self.contrato = self.cliente.contratos_abono.create(
            referencia="AB-61", vigente_desde=date(2020, 1, 1), alcance="Visita preventiva", frecuencia="Mensual",
            cobertura_general=True, valor=Decimal("15000.50"), moneda="ARS", requiere_oc=True,
            requiere_hes=True, portal="Portal ficticio", requisitos_administrativos="Solicitar hoja de servicio.",
        )
        self.alta = reverse("facturacion_abono_mes", args=["2026-11", self.cliente.pk])
        self.datos = {
            "estado": "pendiente", "importe": "16200.50", "moneda": "ars", "ajuste": "Ajuste de ejemplo",
            "requiere_oc": "on", "requiere_hes": "on", "portal": "Portal ficticio", "modalidad": "Primer día hábil",
        }

    def test_control_mensual_precarga_y_conserva_historial_independiente(self):
        form = self.client.get(self.alta).context["form"]
        self.assertEqual(form["importe"].value(), Decimal("15000.50"))
        self.assertTrue(form["requiere_oc"].value())
        self.assertEqual(form["portal"].value(), "Portal ficticio")
        self.assertRedirects(self.client.post(self.alta, self.datos), self.alta)
        registro = self.cliente.facturacion_mensual.get()
        self.assertEqual(registro.contrato, self.contrato)
        self.assertEqual(registro.importe, Decimal("16200.50"))
        listado = self.client.get(reverse("facturacion_abonos"), {"periodo": "2026-11"})
        self.assertContains(listado, "OC pendiente")
        self.assertContains(listado, "HES pendiente")
        self.assertNotContains(listado, self.tercero.nombre)
        self.assertEqual(self.client.post(self.alta, self.datos).status_code, 409)
        otro_mes = reverse("facturacion_abono_mes", args=["2026-12", self.cliente.pk])
        self.assertRedirects(self.client.post(otro_mes, {**self.datos, "importe": "18000"}), otro_mes)
        registro.refresh_from_db()
        self.assertEqual(registro.importe, Decimal("16200.50"))
        self.assertContains(self.client.get(reverse("cliente", args=[self.cliente.pk])), "12/2026")
        self.assertEqual(self.cliente.facturacion_mensual.count(), 2)

    def test_factura_sap_y_respaldo_sin_cerrar_trabajos(self):
        ticket = Ticket.objects.create(asunto="Trabajo abierto", cliente_ficha=self.cliente, creado_por=self.oficina)
        accion = ticket.acciones.create(titulo="Revisar generador", responsable=self.oficina)
        self.client.post(self.alta, self.datos)
        registro = self.cliente.facturacion_mensual.get()
        version = registro.actualizado_el.isoformat()
        factura = {**self.datos, "version": version, "estado": "facturada"}
        respuesta = self.client.post(self.alta, factura)
        for campo in ("factura_sap", "fecha_factura"):
            self.assertTrue(respuesta.context["form"].has_error(campo))
        factura.update(factura_sap="SAP-FICTICIA-61", fecha_factura=timezone.localdate().isoformat(), orden_compra="OC-61")
        self.assertRedirects(self.client.post(self.alta, factura), self.alta)
        self.assertEqual(self.client.post(self.alta, factura).status_code, 409)
        registro.refresh_from_db()
        self.assertEqual(registro.estado, FacturacionMensualAbono.Estado.FACTURADA)
        self.assertEqual(registro.factura_sap, "SAP-FICTICIA-61")
        self.assertIsNone(accion.realizada_el)
        ficha = self.client.get(reverse("cliente", args=[self.cliente.pk]))
        self.assertContains(ficha, "SAP-FICTICIA-61")
        self.assertContains(ficha, "Revisar generador")

    def test_no_corresponde_con_motivo_y_permiso_por_rol(self):
        mes_sin_contrato = reverse("facturacion_abono_mes", args=["2019-12", self.cliente.pk])
        form = self.client.get(mes_sin_contrato).context["form"]
        self.assertEqual(form["estado"].value(), "no_corresponde")
        self.assertContains(self.client.post(mes_sin_contrato, self.datos), "Seleccioná un contrato")
        self.assertRedirects(self.client.post(mes_sin_contrato, {
            "estado": "no_corresponde", "observaciones": "Sin cobertura ese mes.",
        }), mes_sin_contrato)
        self.assertEqual(self.client.get(reverse("facturacion_abono_mes", args=["2026-11", self.tercero.pk])).status_code, 404)
        comercial = User.objects.create_user("comercial.facturacion")
        comercial.groups.add(Group.objects.create(name=Rol.COMERCIAL))
        self.client.force_login(comercial)
        self.assertEqual(self.client.get(self.alta).status_code, 403)
        self.assertNotContains(self.client.get(reverse("cliente", args=[self.cliente.pk])), "Facturación mensual del abono")
