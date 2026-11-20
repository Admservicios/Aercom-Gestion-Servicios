from django.urls import reverse


GRUPOS_OFICINA = (
    ("Seguimiento", None, (
        ("Tickets", "tickets", None),
        ("Pendientes", "pendientes", None),
        ("Recordatorios", "recordatorios", None),
        ("Mis avisos", "avisos_operativos", None),
    )),
    ("Clientes", "clientes", (
        ("Abonados", "abonados", None),
        ("Terceros", "terceros", None),
        ("Equipos", "equipos", None),
    )),
    ("Comercial", None, (
        ("Solicitudes de cotización", "solicitudes_cotizacion", "puede_ver_solicitudes"),
        ("Cotizaciones de terceros", "cotizaciones_terceros", None),
        ("Solicitudes de precios", "solicitudes_precio", "puede_gestionar_cotizaciones"),
    )),
    ("Operación", None, (
        ("Pedidos de servicio", "pedidos_servicio", None),
        ("Agenda", "agenda", None),
        ("Servicios de técnicos", "servicios_tecnicos", None),
    )),
    ("Administración", None, (
        ("Facturación de trabajos", "facturacion_trabajos", None),
        ("Facturación mensual de abonos", "facturacion_abonos", "puede_facturar_abonos"),
        ("Cierre administrativo", "cierre_administrativo", "puede_facturar_abonos"),
    )),
    ("Gestión", None, (
        ("Tiempos por puesto", "tiempos_por_puesto", None),
        ("Tablero de gerencia", "tablero_gerencia", "puede_ver_gerencia"),
        ("Pantalla de oficina", "pantalla_oficina", None),
    )),
)

VISTAS_POR_MODULO = {
    "tickets": ("ticket", "nuevo", "vincular_ticket", "documentos_ticket", "agregar", "cambiar_estado", "realizar"),
    "pendientes": ("proximo_paso_accion",),
    "recordatorios": ("nuevo_recordatorio", "recordatorio_ticket"),
    "avisos_operativos": ("aviso_operativo", "destinatarios_aviso", "gestionar_aviso", "alertas", "nueva_alerta"),
    "clientes": (
        "cliente", "nuevo_cliente", "planta", "nueva_planta", "nuevo_contacto", "editar_contacto",
        "nuevo_documento", "contrato_abono", "nuevo_contrato_abono", "editar_contrato_abono",
    ),
    "equipos": ("equipo", "nuevo_equipo", "editar_equipo", "nuevo_mantenimiento"),
    "solicitudes_cotizacion": (
        "solicitud_cotizacion", "nueva_solicitud_cotizacion", "reenviar_solicitud_cotizacion", "revisar_solicitud_cotizacion",
    ),
    "cotizaciones_terceros": (
        "cotizacion", "nueva_cotizacion", "editar_cotizacion", "cotizar_solicitud", "enviar_cotizacion", "respuesta_cotizacion",
    ),
    "solicitudes_precio": (
        "solicitud_precio", "nueva_solicitud_precio", "responder_solicitud_precio",
        "actualizar_solicitud_precio", "precio_cotizacion", "precio_repuesto",
    ),
    "pedidos_servicio": ("pedido_servicio", "seguimiento_pedido", "pedido_desde_cotizacion", "pedido_por_abono"),
    "agenda": ("visita", "visita_cliente", "visita_pedido", "reprogramar_visita"),
    "servicios_tecnicos": ("servicio_visita", "resultado_visita"),
    "facturacion_trabajos": ("facturacion_trabajo", "actualizar_facturacion_trabajo", "facturar_ticket", "facturar_pedido"),
    "facturacion_abonos": ("facturacion_abono_mes",),
    "cierre_administrativo": ("llamada_sap", "cerrar_llamada_sap", "llamada_sap_ticket", "llamada_sap_facturacion"),
    "tiempos_por_puesto": ("tiempos_accion", "derivar_accion"),
    "tablero_gerencia": ("tablero_casos",),
}
MODULO_POR_VISTA = {vista: modulo for modulo, vistas in VISTAS_POR_MODULO.items() for vista in vistas}


def navegacion_oficina(vista, permisos):
    actual = MODULO_POR_VISTA.get(vista, vista)

    def enlace(ruta):
        return {
            "url": reverse(ruta),
            "actual": "page" if vista == ruta else "location" if actual == ruta else "",
        }

    return {
        "inicio": enlace("inicio"),
        "grupos": [
            {
                "titulo": titulo,
                "enlace": enlace(ruta_grupo) if ruta_grupo else None,
                "activo": actual is not None and (
                    actual == ruta_grupo or any(actual == ruta for _, ruta, _ in accesos)
                ),
                "accesos": [
                    {"titulo": rotulo, **enlace(ruta)}
                    for rotulo, ruta, permiso in accesos if permiso is None or permisos[permiso]
                ],
            }
            for titulo, ruta_grupo, accesos in GRUPOS_OFICINA
        ],
    }
