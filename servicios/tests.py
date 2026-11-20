from datetime import date, timedelta
from decimal import Decimal
from secrets import token_urlsafe

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Accion, AlertaCampo, Cliente, ContratoAbono, Equipo, Planta, RegistroMantenimiento, Ticket
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
