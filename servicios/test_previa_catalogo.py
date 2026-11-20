from dataclasses import replace
from datetime import date
from pathlib import Path

from django.contrib.auth.models import Group, User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import Cliente, ContratoAbono, Equipo, Planta
from .permisos import Rol
from .previa_catalogo import DESGLOSE, DUPLICADO, REVISAR, TRASLADO, comparar_muestra, leer_filas


class PreviaCatalogoTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("admin.previa")
        cls.admin.groups.add(Group.objects.get_or_create(name=Rol.ADMINISTRACION)[0])
        cls.coordinacion = User.objects.create_user("coordinacion.previa")
        cls.coordinacion.groups.add(Group.objects.get_or_create(name=Rol.COORDINACION)[0])
        cls.abonado = Cliente.objects.create(codigo="DEMO-AB-01", nombre="Industrias Horizonte (demo)", tipo="abonado")
        norte = cls.abonado.plantas.create(codigo="DEMO-NORTE", nombre="Planta Norte")
        deposito = cls.abonado.plantas.create(codigo="DEMO-DEPOSITO", nombre="Depósito")
        cls.generador = cls.abonado.equipos.create(
            codigo="DEMO-GE-01", nombre="Generador GE-01", planta=norte, ubicacion="Sala técnica (demo)",
        )
        cls.abonado.equipos.create(codigo="DEMO-CO-02", nombre="Compresor CO-02", planta=deposito)
        contrato = cls.abonado.contratos_abono.create(
            referencia="AB-DEMO-01", vigente_desde=date(2026, 1, 1),
            alcance="Mantenimiento preventivo y lavado del generador en Planta Norte.",
            frecuencia="Mensual", valor=125000, moneda="ARS", requiere_oc=True,
        )
        contrato.plantas.add(norte)
        contrato.equipos.add(cls.generador)

    def test_vista_determinista_y_solo_lectura(self):
        self.client.force_login(self.admin)
        url = reverse("previa_catalogo")
        with CaptureQueriesContext(connection) as consultas:
            primero = self.client.get(url)
            segundo = self.client.get(url)
        self.assertEqual(primero.status_code, 200)
        self.assertEqual(primero.context["secciones"], segundo.context["secciones"])
        self.assertEqual(primero.context["totales"], [
            ("Altas propuestas", 2), ("Coincidencias", 2), ("Duplicados", 1),
            ("Posibles traslados", 1), ("Posibles desgloses", 2), ("Para revisar", 6),
        ])
        self.assertContains(primero, "Repite exactamente la fila 4")
        self.assertContains(primero, "No se encontró la planta SEDE-SIN-CODIGO")
        self.assertContains(primero, "Depende del alta propuesta de FICT-82C-03")
        self.assertContains(primero, "La cobertura depende del equipo FICT-82C-04")
        self.assertContains(primero, "Fila original")
        self.assertContains(primero, "Dato encontrado")
        self.assertContains(primero, "Ver celdas de la fila 3")
        equipos = primero.context["secciones"][0][1]
        traslado = equipos[1]
        self.assertEqual(traslado.estado, TRASLADO)
        self.assertIn("Sede anterior: Depósito (DEMO-DEPOSITO)", traslado.motivo)
        self.assertIn("Sede propuesta: Planta Norte (DEMO-NORTE)", traslado.motivo)
        self.assertIn(("Planta", "Depósito (DEMO-DEPOSITO)"), traslado.encontrados[0].campos)
        contratos = primero.context["secciones"][1][1]
        self.assertEqual(contratos[2].encontrados[0].fuente, "Equipos · Fila 6")
        self.assertEqual([item.estado for item in contratos[3:5]], [DESGLOSE, DESGLOSE])
        self.assertEqual([item.estado for item in contratos[5:7]], [REVISAR, REVISAR])
        self.assertIn("Alcance, Importe", contratos[5].motivo)
        self.assertEqual(contratos[5].encontrados[0].fuente, "Contratos · Fila 8")
        self.assertIn(("Importe", "65000.00"), contratos[5].encontrados[0].campos)
        self.assertIn(("Alcance", "Control preventivo y lavado."), contratos[5].encontrados[0].campos)
        self.assertTrue(all(consulta["sql"].lstrip().startswith("SELECT") for consulta in consultas))
        self.assertEqual((Cliente.objects.count(), Planta.objects.count(), Equipo.objects.count(), ContratoAbono.objects.count()), (1, 2, 2, 1))
        self.assertEqual(self.client.post(url).status_code, 405)
        self.client.force_login(self.coordinacion)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_claves_con_conflicto_y_serie_compartida(self):
        carpeta = Path(__file__).with_name("muestras")
        with (carpeta / "equipos.csv").open(encoding="utf-8") as archivo:
            existentes = leer_filas(archivo, "equipos")
        with (carpeta / "contratos.csv").open(encoding="utf-8") as archivo:
            contratos = leer_filas(archivo, "contratos")
        fila = existentes[2]
        conflicto = replace(existentes[3], datos={**fila.datos, "nombre": "Nombre diferente"})
        equipos, informe = comparar_muestra([*existentes[:3], conflicto, existentes[4]], contratos)
        self.assertEqual([item.estado for item in equipos[2:4]], [REVISAR, REVISAR])
        self.assertIn("filas 4, 5", equipos[2].motivo)
        self.assertEqual(informe[1].estado, REVISAR)

        self.generador.numero_serie = fila.datos["numero_serie"]
        self.generador.save(update_fields=["numero_serie"])
        equipos, _ = comparar_muestra(existentes, contratos)
        self.assertEqual(equipos[0].estado, REVISAR)
        self.assertIn("número de serie", equipos[0].motivo.lower())
        self.assertEqual(equipos[2].estado, REVISAR)
        self.assertIn("La misma serie", equipos[2].motivo)
        self.assertIn(("Código", self.generador.codigo), equipos[2].encontrados[0].campos)

    def test_cobertura_equivalente_se_repite_y_vinculos_pendientes_se_conservan(self):
        carpeta = Path(__file__).with_name("muestras")
        with (carpeta / "equipos.csv").open(encoding="utf-8") as archivo:
            equipos = leer_filas(archivo, "equipos")
        with (carpeta / "contratos.csv").open(encoding="utf-8") as archivo:
            contratos = leer_filas(archivo, "contratos")
        norte, deposito = contratos[3:5]
        copia = replace(norte, numero=9, datos={**norte.datos, "valor": "45000", "moneda": "ars"})
        _, informados = comparar_muestra(equipos, [norte, deposito, copia])
        self.assertEqual([item.estado for item in informados], [DESGLOSE, DESGLOSE, DUPLICADO])
        pendiente = replace(deposito, datos={**deposito.datos, "equipos_codigos": "FICT-82C-04"})
        _, informados = comparar_muestra(equipos, [norte, pendiente])
        self.assertTrue(all(item.estado == REVISAR and "FICT-82C-04" in item.motivo for item in informados))

        equipo = equipos[1]
        con_otro_cambio = replace(equipo, datos={**equipo.datos, "ubicacion": "Nuevo lugar"})
        informados, _ = comparar_muestra([con_otro_cambio], [])
        self.assertEqual(informados[0].estado, REVISAR)
        self.assertIn("ubicación", informados[0].motivo.lower())
