"""Concepts of the synthetic corpus, each with several vocabularies that say the
same thing in different words. The generated text is Spanish, like the real
sources. No two vocabularies of one concept share a content word (checked by a
test); different concepts do share words, which is what makes lexical search
retrieve the wrong documents."""
from __future__ import annotations

from dataclasses import dataclass

VOCABULARIES = 3


@dataclass(frozen=True)
class Concept:
    key: str
    variants: tuple[str, ...]


@dataclass(frozen=True)
class Family:
    """Documents of one nature. A topic is a kind, a subject and an aspect."""

    key: str
    section: int
    kinds: tuple[Concept, ...]
    subjects: tuple[Concept, ...]


def _concepts(prefix: str, table: str) -> tuple[Concept, ...]:
    concepts = []
    for line in table.strip().splitlines():
        key, *variants = (part.strip() for part in line.split("|"))
        concepts.append(Concept(f"{prefix}.{key}", tuple(variants)))
    return tuple(concepts)


WORKS = Family(
    "works",
    4,
    _concepts(
        "works.kind",
        """
        tender | licitación pública | llamado a ofertar | concurso de precios
        direct | compra directa | contratación abreviada | adjudicación simple
        auction | subasta electrónica inversa | puja digital descendente | remate virtual a la baja
        amendment | enmienda de pliego | nota aclaratoria de bases | modificación de condiciones
        extension | prórroga de apertura | postergación del acto de sobres | nuevo plazo para presentar propuestas
        """,
    ),
    _concepts(
        "works.subject",
        """
        paving | pavimentación de calzada | carpeta asfáltica vial | recubrimiento bituminoso de ruta
        bridge | puente vehicular | viaducto carretero | paso elevado sobre cauce
        school | edificio escolar | establecimiento educativo | aulas de nivel primario
        hospital | hospital regional | centro asistencial de salud | nosocomio zonal
        water | red de agua potable | acueducto domiciliario | cañería para suministro hídrico
        sewer | desagües cloacales | colector de efluentes sanitarios | saneamiento de líquidos residuales
        lighting | alumbrado público | luminarias led de calle | iluminación urbana
        tires | neumáticos para rodados | cubiertas de vehículos | gomas automotor
        computers | computadoras portátiles | notebooks de escritorio | equipos informáticos
        drugs | medicamentos oncológicos | fármacos de alto costo | drogas terapéuticas
        food | alimentos perecederos | víveres frescos | provisiones para comedor
        cleaning | servicio de limpieza | higiene de oficinas | aseo integral
        guards | vigilancia privada | custodia de edificios | seguridad física de dependencias
        waste | contenedores de residuos | volquetes para basura | recipientes de desechos
        ambulances | ambulancias equipadas | móviles de traslado sanitario | unidades de emergencia médica
        uniforms | uniformes de trabajo | indumentaria laboral | vestuario del personal
        furniture | mobiliario de oficina | escritorios y sillas | equipamiento en madera
        fuel | combustible líquido | gasoil y nafta | carburante a granel
        stationery | resmas de papel | artículos de librería | insumos para impresión
        irrigation | sistema de riego | canales para cultivos | distribución agrícola por aspersión
        gas | gasoducto troncal | ampliación de red gasífera | tendido de gas natural
        solar | paneles fotovoltaicos | parque de energía solar | generación renovable distribuida
        lifts | mantenimiento de ascensores | reparación de elevadores | conservación de montacargas
        software | licencias de software | programas informáticos de gestión | desarrollo de plataforma web
        """,
    ),
)

COMPANIES = Family(
    "companies",
    3,
    _concepts(
        "companies.kind",
        """
        incorporation | constitución de sociedad | contrato social fundacional | creación de firma comercial
        meeting | convocatoria a asamblea ordinaria | citación a reunión de accionistas | llamado a junta de socios
        reform | reforma de estatuto | cambio del texto constitutivo | adecuación de cláusulas orgánicas
        officers | elección de autoridades | designación de directorio | nombramiento de gerentes
        dissolution | disolución anticipada | liquidación del patrimonio | cese definitivo de actividades
        """,
    ),
    _concepts(
        "companies.subject",
        """
        farming | explotación agropecuaria | producción de granos | cría de ganado
        building | empresa constructora | edificación de viviendas | emprendimientos de albañilería
        catering | rubro gastronómico | bares y restaurantes | elaboración de comidas
        freight | transporte de cargas | logística de mercaderías | fletes de larga distancia
        textile | fabricación textil | confección de prendas | hilandería de algodón
        pharmacy | farmacia y perfumería | droguería mayorista | expendio de remedios
        realty | corretaje inmobiliario | administración de propiedades | alquiler de inmuebles
        tourism | agencia de turismo | hotelería y excursiones | organización de viajes
        mining | explotación minera | extracción de áridos | cantera de mármol
        metal | industria metalúrgica | fundición de acero | taller de tornería
        teaching | instituto de enseñanza | capacitación profesional | academia de idiomas
        clinic | clínica privada | sanatorio modelo | consultorios médicos
        """,
    ),
)

COURTS = Family(
    "courts",
    2,
    _concepts(
        "courts.kind",
        """
        succession | declaratoria de herederos | juicio sucesorio | acervo del causante
        bankruptcy | quiebra decretada | concurso preventivo | insolvencia del deudor
        adverse | usucapión promovida | prescripción adquisitiva | posesión veinteañal
        sale | remate judicial | subasta por martillero | venta forzada de bienes
        cancellation | cancelación de título | extravío de cheque | anulación del pagaré
        """,
    ),
    _concepts(
        "courts.subject",
        """
        house | casa habitación | vivienda unifamiliar | inmueble residencial
        field | fracción de campo | lote rural | parcela de tierra agrícola
        garage | cochera cubierta | espacio para estacionar | garaje en subsuelo
        truck | camión con acoplado | vehículo pesado de carga | tractor y semirremolque
        machinery | maquinaria vial | retroexcavadora hidráulica | equipo pesado de obra
        shop | local comercial | salón de ventas | tienda a la calle
        flat | departamento en propiedad horizontal | unidad funcional | piso de edificio
        motorbike | motocicleta registrada | ciclomotor urbano | rodado de dos ruedas
        plot | terreno baldío | solar sin mejoras | predio desocupado
        shed | galpón industrial | nave de depósito | tinglado fabril
        """,
    ),
)

NOTIFICATIONS = Family(
    "notifications",
    4,
    _concepts(
        "notifications.kind",
        """
        refund | reintegro de haberes | devolución de sueldos percibidos | recupero de salarios
        fine | multa impuesta | sanción pecuniaria | penalidad económica
        tax | deuda tributaria | obligación fiscal impaga | impuestos adeudados
        inquiry | sumario administrativo | investigación disciplinaria | actuaciones por falta
        """,
    ),
    _concepts(
        "notifications.subject",
        """
        teacher | docente suplente | maestra de grado | profesor interino
        police | agente policial | suboficial de la fuerza | efectivo retirado
        trader | comercio minorista | almacén de barrio | kiosco habilitado
        driver | conductor infractor | chofer sin licencia | automovilista imprudente
        owner | propietario registral | dueño del dominio | titular catastral
        contractor | contratista incumplidor | proveedor moroso | adjudicatario en mora
        nurse | personal de enfermería | auxiliar sanitario | cuidadora hospitalaria
        producer | productor rural | chacarero arrendatario | tambero de la zona
        roads | consorcio caminero | ente vecinal de mantenimiento | junta de conservación
        retired | jubilado provincial | beneficiario de pensión | pasivo de la caja
        """,
    ),
)

RULES = Family(
    "rules",
    1,
    _concepts(
        "rules.kind",
        """
        decree | decreto del poder ejecutivo | disposición del gobernador | mandato de la primera magistratura
        resolution | resolución ministerial | acto administrativo del secretario | pronunciamiento de la cartera
        ordinance | ordenanza municipal | norma del concejo deliberante | regla comunal
        law | ley sancionada | legislación aprobada por diputados | texto legal promulgado
        """,
    ),
    _concepts(
        "rules.subject",
        """
        budget | presupuesto general de gastos | cálculo de recursos | partidas financieras
        traffic | ordenamiento del tránsito | circulación vehicular | estacionamiento medido
        environment | protección ambiental | cuidado del ecosistema | preservación de bosques
        housing | plan habitacional | programa de casas sociales | créditos para techo propio
        heritage | patrimonio cultural | monumento histórico | bienes de valor artístico
        grants | becas estudiantiles | ayuda económica a alumnos | subsidio escolar
        fares | tarifa de servicios | cuadro de precios regulados | boleto del transporte
        health | emergencia sanitaria | campaña de vacunación | prevención epidemiológica
        fires | riesgo de incendios | quema de pastizales | lucha contra el fuego
        jobs | fomento del empleo | incorporación laboral de jóvenes | generación de puestos
        sport | actividad deportiva | clubes y torneos | competencias atléticas
        holiday | asueto administrativo | día no laborable | jornada de descanso
        """,
    ),
)

FAMILIES = (WORKS, COMPANIES, COURTS, NOTIFICATIONS, RULES)

ASPECTS = _concepts(
    "aspect",
    """
    urgent | con carácter urgente | por razones de apremio | de manera inmediata
    second | en segundo llamado | por haber fracasado la instancia anterior | tras quedar desierto el primero
    funded | con financiamiento externo | mediante préstamo del banco | costeado por organismo multilateral
    multiyear | con ejecución plurianual | a desarrollarse en varios ejercicios | por etapas sucesivas
    corrected | con rectificación de errores | salvando una omisión material | corrigiendo datos equivocados
    inland | destinado al interior provincial | para localidades del norte | en departamentos alejados
    women | con perspectiva de género | favoreciendo a mujeres | según cupo femenino
    access | con criterios de accesibilidad | apto para personas con discapacidad | sin barreras arquitectónicas
    online | por vía telemática | con expediente digital | a través del portal en línea
    exception | por vía de excepción | fuera del régimen ordinario | en forma extraordinaria
    """,
)


def all_concepts() -> list[Concept]:
    return [c for f in FAMILIES for c in (*f.kinds, *f.subjects)] + list(ASPECTS)
