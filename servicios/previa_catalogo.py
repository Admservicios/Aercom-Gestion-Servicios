from collections import Counter, defaultdict
from csv import DictReader
from dataclasses import dataclass
from datetime import date
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
TRASLADO = "Posible traslado"
DESGLOSE = "Posible desglose de cobertura"

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
ROTULOS = {
    "codigo": "Código", "cliente_codigo": "Código de cliente", "planta_codigo": "Código de planta",
    "plantas_codigos": "Plantas cubiertas", "equipos_codigos": "Equipos cubiertos",
    "valor": "Importe", "numero_serie": "Número de serie", "ubicacion": "Ubicación",
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
    celdas: dict[str, str] | None = None

    @property
    def identificacion(self):
        return " · ".join(valor or "Sin dato" for valor in self.clave)


    @property
    def datos_originales(self):
        return datos_rotulados(self.celdas if self.celdas is not None else self.datos)


@dataclass(frozen=True)
class Hallazgo:
    fuente: str
    campos: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Resultado:
    fila: Fila
    estado: str
    motivo: str
    encontrados: tuple[Hallazgo, ...] = ()


def rotulo(campo):
    return ROTULOS.get(campo, campo.replace("_", " ").capitalize())


def datos_rotulados(datos):
    return tuple((rotulo(campo), valor or "—") for campo, valor in datos.items())


def hallazgo_fila(fila, campos):
    origen = fila.celdas if fila.celdas is not None else fila.datos
    hoja = "Equipos" if "planta_codigo" in origen else "Contratos"
    return Hallazgo(f"{hoja} · Fila {fila.numero}", datos_rotulados({campo: origen[campo] for campo in campos}))


def sede(planta):
    return f"{planta.nombre} ({planta.codigo})" if planta else "Sin planta registrada"


def hallazgo_equipo(equipo):
    return Hallazgo("Ficha existente", datos_rotulados({
        **{campo: getattr(equipo, campo) for campo in CAMPOS_EQUIPO}, "planta": sede(equipo.planta),
    }))


def hallazgo_contrato(contrato, campos=()):
    return Hallazgo("Contrato existente", datos_rotulados({
        "referencia": contrato.referencia,
        "vigente_desde": contrato.vigente_desde.isoformat(),
        "valor": str(contrato.valor),
        "moneda": contrato.moneda,
        "alcance": contrato.alcance,
        "plantas_codigos": ", ".join(sorted(p.codigo for p in contrato.plantas.all())),
        "equipos_codigos": ", ".join(sorted(e.codigo for e in contrato.equipos.all())),
        **{campo: str(getattr(contrato, campo)) for campo in campos if campo in CAMPOS_CONTRATO},
    }))


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
        filas.append(Fila(numero, tuple(datos[campo] for campo in CLAVES[tipo]), datos, celdas))
    return filas


def evaluar_filas(filas, evaluar, comparar_grupo):
    por_clave = defaultdict(list)
    for fila in filas:
        por_clave[fila.clave].append(fila)
    resultados = []
    for clave, grupo in por_clave.items():
        primera, *otras = grupo
        if not all(clave):
            resultados.extend(Resultado(fila, REVISAR, "Faltan datos en la clave del registro.") for fila in grupo)
        elif any(fila.datos != primera.datos for fila in otras):
            resultados.extend(comparar_grupo(grupo))
        else:
            try:
                resultados.append(evaluar(primera))
            except ValidationError as error:
                resultados.append(Resultado(primera, REVISAR, " ".join(error.messages)))
            resultados.extend(duplicado(fila, primera) for fila in otras)
    return sorted(resultados, key=lambda item: item.fila.numero)


def duplicado(fila, primera, exacto=True):
    motivo = (
        f"Repite exactamente la fila {primera.numero} de esta muestra." if exacto
        else f"Repite los datos de la fila {primera.numero} con otro formato."
    )
    campos = CLAVES["equipos"] if "codigo" in primera.datos else CLAVES["contratos"]
    return Resultado(fila, DUPLICADO, motivo, (hallazgo_fila(primera, campos),))


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
            "plantas", "equipos__planta", "contratos_abono__plantas", "contratos_abono__equipos",
        )
    }
    plantas = {(c.codigo, p.codigo): p for c in clientes.values() for p in c.plantas.all()}
    equipos = {(c.codigo, e.codigo): e for c in clientes.values() for e in c.equipos.all()}
    contratos = {
        (c.codigo, a.referencia, a.vigente_desde): a
        for c in clientes.values() for a in c.contratos_abono.all()
    }
    fichas_por_serie = defaultdict(dict)
    for (codigo_cliente, codigo_equipo), equipo in equipos.items():
        if equipo.numero_serie:
            fichas_por_serie[(codigo_cliente, equipo.numero_serie.strip().casefold())][codigo_equipo] = hallazgo_equipo(equipo)
    for fila in filas_equipos:
        if all(fila.clave) and fila.datos["numero_serie"]:
            serie = fila.datos["numero_serie"].casefold()
            fichas_por_serie[(fila.clave[0], serie)].setdefault(
                fila.clave[1], hallazgo_fila(fila, ("codigo", "planta_codigo", "numero_serie")),
            )

    def evaluar_equipo(fila):
        codigo_cliente, codigo_equipo = fila.clave
        existente = equipos.get(fila.clave)
        encontrado = (hallazgo_equipo(existente),) if existente else ()
        if codigo_cliente not in clientes:
            return Resultado(fila, REVISAR, f"No se encontró el cliente {codigo_cliente}.")
        referencia = fila.datos["planta_codigo"]
        planta = plantas.get((codigo_cliente, referencia))
        serie = fila.datos["numero_serie"]
        otros = fichas_por_serie.get((codigo_cliente, serie.casefold()), {})
        otros_codigos = sorted(set(otros) - {codigo_equipo})
        motivos = []
        if not referencia:
            motivos.append("Falta el código de planta. Confirmá la sede del equipo.")
        elif planta is None:
            motivos.append(f"No se encontró la planta {referencia} para el cliente {codigo_cliente}.")
        if otros_codigos and (existente is None or serie != existente.numero_serie):
            motivos.append(f"La misma serie figura con otro código de equipo: {', '.join(otros_codigos)}.")
            encontrado += tuple(otros[codigo] for codigo in otros_codigos)
        if motivos:
            return Resultado(fila, REVISAR, " ".join(motivos), encontrado)

        valores = {campo: fila.datos[campo] for campo in CAMPOS_EQUIPO}
        candidato = Equipo(cliente=clientes[codigo_cliente], planta=planta, **valores)
        try:
            candidato.full_clean(validate_unique=False, validate_constraints=False)
        except ValidationError as error:
            return Resultado(fila, REVISAR, " ".join(error.messages), encontrado)
        if existente and candidato.planta_id != existente.planta_id and all(
            getattr(candidato, campo) == getattr(existente, campo) for campo in CAMPOS_EQUIPO
        ):
            if existente.planta_id is None:
                return Resultado(fila, REVISAR, "La ficha no tiene planta anterior. Confirmá la asignación de sede.", encontrado)
            motivo = f"Sede anterior: {sede(existente.planta)}. Sede propuesta: {sede(planta)}."
            return Resultado(fila, TRASLADO, motivo, encontrado)
        estado, motivo = comparar(candidato, existente, (*CAMPOS_EQUIPO, "planta"))
        return Resultado(fila, estado, motivo, encontrado)

    def comparar_grupo_equipos(grupo):
        numeros = ", ".join(str(fila.numero) for fila in grupo)
        campos = (*CAMPOS_EQUIPO, "planta_codigo")
        existente = equipos.get(grupo[0].clave)
        encontrado = (hallazgo_equipo(existente),) if existente else ()
        return [
            Resultado(fila, REVISAR, f"La misma clave tiene datos distintos en las filas {numeros}.", (
                *encontrado, *(hallazgo_fila(otra, campos) for otra in grupo if otra.datos != fila.datos),
            ))
            for fila in grupo
        ]

    informe_equipos = evaluar_filas(filas_equipos, evaluar_equipo, comparar_grupo_equipos)
    nuevos = {item.fila.clave for item in informe_equipos if item.estado == CREAR}
    equipos_en_revision = {
        item.fila.clave: item.fila for item in informe_equipos if item.estado == REVISAR
    }

    def equipos_asociados(fila):
        return {codigo.strip() for codigo in fila.datos["equipos_codigos"].split("|") if codigo.strip()}

    def equipos_pendientes(fila):
        cliente = fila.clave[0]
        return tuple(
            hallazgo_fila(equipos_en_revision[(cliente, codigo)], ("codigo", "planta_codigo", "numero_serie"))
            for codigo in sorted(equipos_asociados(fila)) if (cliente, codigo) in equipos_en_revision
        )

    def preparar_contrato(fila):
        codigo_cliente = fila.clave[0]
        cliente = clientes.get(codigo_cliente)
        if cliente is None or cliente.tipo != Cliente.Tipo.ABONADO:
            raise ValidationError(f"El código {codigo_cliente} debe corresponder a un abonado existente.")
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
                raise ValidationError("Usá fechas AAAA-MM-DD en esta muestra.")
        sedes = {codigo.strip() for codigo in fila.datos["plantas_codigos"].split("|") if codigo.strip()}
        maquinas = equipos_asociados(fila)
        if candidato.cobertura_general == bool(sedes or maquinas):
            raise ValidationError("Indicá cobertura general o plantas y equipos específicos, según el contrato.")
        return candidato, sedes, maquinas

    def validar_referencias(codigo_cliente, sedes, maquinas):
        for codigo in sorted(sedes):
            if (codigo_cliente, codigo) not in plantas:
                raise ValidationError(f"La planta cubierta {codigo} no se encontró para el abonado.")
        for codigo in sorted(maquinas):
            clave = (codigo_cliente, codigo)
            if clave in equipos_en_revision:
                raise ValidationError(f"La cobertura depende del equipo {codigo}, que está en revisión.")
            if clave not in equipos and clave not in nuevos:
                raise ValidationError(f"El equipo cubierto {codigo} no se encontró para el abonado.")

    def contrato_existente(clave):
        cliente, referencia, inicio = clave
        try:
            fecha = date.fromisoformat(inicio)
        except ValueError:
            return None
        return contratos.get((cliente, referencia, fecha))

    def evaluar_contrato(fila, preparado=None):
        existente = contrato_existente(fila.clave)
        encontrado = (hallazgo_contrato(existente),) if existente else ()
        if preparado is None:
            try:
                preparado = preparar_contrato(fila)
                validar_referencias(fila.clave[0], *preparado[1:])
            except ValidationError as error:
                return Resultado(fila, REVISAR, " ".join(error.messages), (*encontrado, *equipos_pendientes(fila)))
        candidato, sedes, maquinas = preparado
        diferencias = []
        if existente:
            if sedes != {p.codigo for p in existente.plantas.all()}:
                diferencias.append("plantas cubiertas")
            if maquinas != {e.codigo for e in existente.equipos.all()}:
                diferencias.append("equipos cubiertos")
        estado, motivo = comparar(candidato, existente, CAMPOS_CONTRATO, diferencias)
        propuestos = sorted(codigo for codigo in maquinas if (fila.clave[0], codigo) in nuevos)
        if estado == CREAR and propuestos:
            motivo += f" Depende del alta propuesta de {', '.join(propuestos)}."
        return Resultado(fila, estado, motivo, encontrado)

    def comparar_grupo_contratos(grupo):
        primera = grupo[0]
        existente = contrato_existente(primera.clave)
        preparados = []
        errores = []
        for fila in grupo:
            try:
                preparado = preparar_contrato(fila)
                preparados.append(preparado)
                validar_referencias(fila.clave[0], *preparado[1:])
            except ValidationError as error:
                errores.append(f"Fila {fila.numero}: {' '.join(error.messages)}")
        campos = ()
        cambios_con_ficha = ()
        candidato = preparados[0][0] if preparados else None
        if candidato:
            campos = tuple(
                campo for campo in CAMPOS_CONTRATO
                if any(getattr(item[0], campo) != getattr(candidato, campo) for item in preparados[1:])
            )
            cambios_con_ficha = tuple(
                campo for campo in CAMPOS_CONTRATO
                if existente and getattr(existente, campo) != getattr(candidato, campo)
            )
        if campos:
            errores.insert(0, f"Las filas con la misma clave difieren en {', '.join(map(rotulo, campos))}. Falta confirmar qué fuente prevalece.")
        if cambios_con_ficha and not campos:
            errores.append(f"Los datos del contrato existente difieren en {', '.join(map(rotulo, cambios_con_ficha))}. Falta confirmar qué fuente prevalece.")

        if errores:
            estado, motivo = REVISAR, " ".join(errores)
        elif all(item[1:] == preparados[0][1:] for item in preparados[1:]):
            return [evaluar_contrato(primera, preparados[0]), *(duplicado(fila, primera, exacto=False) for fila in grupo[1:])]
        else:
            estado = DESGLOSE
            motivo = "Las filas comparten la clave y los datos del contrato. Solo cambian las plantas o equipos cubiertos."

        campos_comparados = tuple(dict.fromkeys(("plantas_codigos", "equipos_codigos", "valor", "moneda", "alcance", *campos)))
        ficha = (hallazgo_contrato(existente, cambios_con_ficha),) if existente else ()
        resultados = []
        primera_por_cobertura = {}
        for i, fila in enumerate(grupo):
            if estado == DESGLOSE:
                _, sedes, maquinas = preparados[i]
                cobertura = (frozenset(sedes), frozenset(maquinas))
                original = primera_por_cobertura.setdefault(cobertura, fila)
                if original is not fila:
                    resultados.append(duplicado(fila, original, exacto=fila.datos == original.datos))
                    continue
            encontrados = (
                *(hallazgo_fila(otra, campos_comparados) for otra in grupo if otra.datos != fila.datos),
                *ficha, *equipos_pendientes(fila),
            )
            resultados.append(Resultado(fila, estado, motivo, encontrados))
        return resultados

    return informe_equipos, evaluar_filas(filas_contratos, evaluar_contrato, comparar_grupo_contratos)


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
        (DUPLICADO, "Duplicados"), (TRASLADO, "Posibles traslados"),
        (DESGLOSE, "Posibles desgloses"), (REVISAR, "Para revisar"),
    )
    return render(request, "servicios/previa_catalogo.html", {
        "secciones": (("Equipos", equipos), ("Contratos", contratos)),
        "totales": [(titulo, totales[estado]) for estado, titulo in indicadores],
    })
