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
from .previa_catalogo import REVISAR, comparar_muestra, leer_filas


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
            ("Altas propuestas", 2), ("Coincidencias", 3), ("Duplicados", 1), ("Para revisar", 2),
        ])
        self.assertContains(primero, "Repite exactamente la fila 4")
        self.assertContains(primero, "No se encontró la planta SEDE-SIN-CODIGO")
        self.assertContains(primero, "Depende del alta propuesta de FICT-82C-03")
        self.assertContains(primero, "La cobertura depende del equipo FICT-82C-04")
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
