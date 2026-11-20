from collections import Counter, defaultdict
from csv import DictReader
from dataclasses import dataclass
from pathlib import Path

from django.core.exceptions import ValidationError
from django.shortcuts import render
from django.views.decorators.http import require_safe

from .models import Cliente, ContratoAbono, Equipo
from .permisos import edicion_catalogo_requerida


CREAR = "Se crearía"
COINCIDE = "Coincide"
DUPLICADO = "Duplicado"
REVISAR = "Revisar"

CAMPOS_EQUIPO = ("codigo", "nombre", "numero_serie", "ubicacion")
CAMPOS_CONTRATO = (
    "referencia", "vigente_desde", "vigente_hasta", "alcance", "frecuencia",
    "cobertura_general", "valor", "moneda", "requiere_oc", "requiere_hes", "portal",
    "requisitos_administrativos",
)
BOOLEANOS = ("cobertura_general", "requiere_oc", "requiere_hes")
ARCHIVOS = {
    "equipos": ("cliente_codigo", "planta_codigo", *CAMPOS_EQUIPO),
    "contratos": ("cliente_codigo", "plantas_codigos", "equipos_codigos", *CAMPOS_CONTRATO),
}
CLAVES = {
    "equipos": ("cliente_codigo", "codigo"),
    "contratos": ("cliente_codigo", "referencia", "vigente_desde"),
}


@dataclass(frozen=True)
class Fila:
    numero: int
    clave: tuple[str, ...]
    datos: dict[str, str]

    @property
    def identificacion(self):
        return " · ".join(valor or "Sin dato" for valor in self.clave)


@dataclass(frozen=True)
class Resultado:
    fila: Fila
    estado: str
    motivo: str


def leer_filas(origen, tipo):
    lector = DictReader(origen)
    columnas = ARCHIVOS[tipo]
    if len(lector.fieldnames or ()) != len(columnas) or set(lector.fieldnames or ()) != set(columnas):
        raise ValueError(f"Los encabezados de {tipo} no corresponden a la muestra.")
    filas = []
    for numero, celdas in enumerate(lector, start=2):
        if None in celdas or None in celdas.values():
            raise ValueError(f"La fila {numero} de {tipo} tiene un número de celdas incorrecto.")
        datos = {campo: valor.strip() for campo, valor in celdas.items()}
        filas.append(Fila(numero, tuple(datos[campo] for campo in CLAVES[tipo]), datos))
    return filas


def evaluar_filas(filas, evaluar):
    por_clave = defaultdict(list)
    for fila in filas:
        por_clave[fila.clave].append(fila)
    for fila in filas:
        grupo = por_clave[fila.clave]
        primera = grupo[0]
        if not all(fila.clave):
            yield Resultado(fila, REVISAR, "Faltan datos en la clave del registro.")
        elif any(item.datos != primera.datos for item in grupo):
            numeros = ", ".join(str(item.numero) for item in grupo)
            yield Resultado(fila, REVISAR, f"La misma clave tiene datos distintos en las filas {numeros}.")
        elif fila is not primera:
            yield Resultado(fila, DUPLICADO, f"Repite exactamente la fila {primera.numero} de esta muestra.")
        else:
            try:
                estado, motivo = evaluar(fila)
            except ValidationError as error:
                estado, motivo = REVISAR, " ".join(error.messages)
            yield Resultado(fila, estado, motivo)


def comparar(candidato, existente, campos, diferencias=()):
    if existente is None:
        return CREAR, "Clave nueva. Las referencias y los campos requeridos son válidos."
    cambios = [
        str(candidato._meta.get_field(campo).verbose_name)
        for campo in campos if getattr(candidato, campo) != getattr(existente, campo)
    ]
    cambios.extend(diferencias)
    if cambios:
        return REVISAR, f"La clave ya existe y difieren estos campos: {', '.join(cambios)}."
    return COINCIDE, "La clave y los campos comparados coinciden con el registro existente."


def comparar_muestra(filas_equipos, filas_contratos):
    codigos = {fila.clave[0] for fila in filas_equipos + filas_contratos}
    clientes = {
        cliente.codigo: cliente
        for cliente in Cliente.objects.filter(codigo__in=codigos).prefetch_related(
            "plantas", "equipos", "contratos_abono__plantas", "contratos_abono__equipos",
        )
    }
    plantas = {(c.codigo, p.codigo): p for c in clientes.values() for p in c.plantas.all()}
    equipos = {(c.codigo, e.codigo): e for c in clientes.values() for e in c.equipos.all()}
    contratos = {
        (c.codigo, a.referencia, a.vigente_desde): a
        for c in clientes.values() for a in c.contratos_abono.all()
    }
    codigos_por_serie = defaultdict(set)
    for (codigo_cliente, codigo_equipo), equipo in equipos.items():
        if equipo.numero_serie:
            codigos_por_serie[(codigo_cliente, equipo.numero_serie.strip().casefold())].add(codigo_equipo)
    for fila in filas_equipos:
        if all(fila.clave) and fila.datos["numero_serie"]:
            codigos_por_serie[(fila.clave[0], fila.datos["numero_serie"].casefold())].add(fila.clave[1])

    def evaluar_equipo(fila):
        codigo_cliente, codigo_equipo = fila.clave
        if codigo_cliente not in clientes:
            return REVISAR, f"No se encontró el cliente {codigo_cliente}."
        referencia = fila.datos["planta_codigo"]
        planta = plantas.get((codigo_cliente, referencia))
        if not referencia:
            return REVISAR, "Falta el código de planta. Confirmá la sede del equipo."
        if planta is None:
            return REVISAR, f"No se encontró la planta {referencia} para el cliente {codigo_cliente}."

        valores = {campo: fila.datos[campo] for campo in CAMPOS_EQUIPO}
        candidato = Equipo(cliente=clientes[codigo_cliente], planta=planta, **valores)
        candidato.full_clean(validate_unique=False, validate_constraints=False)
        otros_codigos = codigos_por_serie.get((codigo_cliente, candidato.numero_serie.casefold()), set()) - {codigo_equipo}
        if otros_codigos:
            return REVISAR, f"La misma serie figura con otro código de equipo: {', '.join(sorted(otros_codigos))}."
        return comparar(candidato, equipos.get(fila.clave), (*CAMPOS_EQUIPO, "planta"))

    informe_equipos = list(evaluar_filas(filas_equipos, evaluar_equipo))
    nuevos = {item.fila.clave for item in informe_equipos if item.estado == CREAR}
    equipos_en_revision = {item.fila.clave for item in informe_equipos if item.estado == REVISAR}

    def evaluar_contrato(fila):
        codigo_cliente = fila.clave[0]
        cliente = clientes.get(codigo_cliente)
        if cliente is None or cliente.tipo != Cliente.Tipo.ABONADO:
            return REVISAR, f"El código {codigo_cliente} debe corresponder a un abonado existente."
        valores = {campo: fila.datos[campo] for campo in CAMPOS_CONTRATO}
        for campo in BOOLEANOS:
            valor = valores[campo].lower()
            if valor not in ("si", "sí", "no"):
                raise ValidationError(f"Indicá sí o no en {campo}.")
            valores[campo] = valor != "no"
        valores["vigente_hasta"] = valores["vigente_hasta"] or None
        valores["moneda"] = valores["moneda"].upper()
        candidato = ContratoAbono(cliente=cliente, **valores)
        candidato.full_clean(validate_unique=False, validate_constraints=False)

        for campo in ("vigente_desde", "vigente_hasta"):
            fecha = getattr(candidato, campo)
            if fecha and fecha.isoformat() != valores[campo]:
                return REVISAR, "Usá fechas AAAA-MM-DD en esta muestra."
        sedes = {codigo.strip() for codigo in fila.datos["plantas_codigos"].split("|") if codigo.strip()}
        maquinas = {codigo.strip() for codigo in fila.datos["equipos_codigos"].split("|") if codigo.strip()}
        if candidato.cobertura_general == bool(sedes or maquinas):
            return REVISAR, "Indicá cobertura general o plantas y equipos específicos, según el contrato."
        for codigo in sorted(sedes):
            if (codigo_cliente, codigo) not in plantas:
                return REVISAR, f"La planta cubierta {codigo} no se encontró para el abonado."
        for codigo in sorted(maquinas):
            clave = (codigo_cliente, codigo)
            if clave in equipos_en_revision:
                return REVISAR, f"La cobertura depende del equipo {codigo}, que está en revisión."
            if clave not in equipos and clave not in nuevos:
                return REVISAR, f"El equipo cubierto {codigo} no se encontró para el abonado."

        existente = contratos.get((codigo_cliente, candidato.referencia, candidato.vigente_desde))
        diferencias = []
        if existente:
            if sedes != {p.codigo for p in existente.plantas.all()}:
                diferencias.append("plantas cubiertas")
            if maquinas != {e.codigo for e in existente.equipos.all()}:
                diferencias.append("equipos cubiertos")
        estado, motivo = comparar(candidato, existente, CAMPOS_CONTRATO, diferencias)
        propuestos = sorted(codigo for codigo in maquinas if (codigo_cliente, codigo) in nuevos)
        if estado == CREAR and propuestos:
            motivo += f" Depende del alta propuesta de {', '.join(propuestos)}."
        return estado, motivo

    return informe_equipos, list(evaluar_filas(filas_contratos, evaluar_contrato))


@edicion_catalogo_requerida
@require_safe
def previa_catalogo(request):
    carpeta = Path(__file__).with_name("muestras")
    filas = []
    for tipo in ARCHIVOS:
        with (carpeta / f"{tipo}.csv").open(encoding="utf-8-sig", newline="") as archivo:
            filas.append(leer_filas(archivo, tipo))
    equipos, contratos = comparar_muestra(*filas)
    totales = Counter(item.estado for item in equipos + contratos)
    indicadores = (
        (CREAR, "Altas propuestas"), (COINCIDE, "Coincidencias"),
        (DUPLICADO, "Duplicados"), (REVISAR, "Para revisar"),
    )
    return render(request, "servicios/previa_catalogo.html", {
        "secciones": (("Equipos", equipos), ("Contratos", contratos)),
        "totales": [(titulo, totales[estado]) for estado, titulo in indicadores],
    })
