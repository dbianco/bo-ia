"""Deterministic corpus of gazette or tender documents with planted relevance.

Relevance is known by construction. A document is built from a topic (kind,
subject and aspect) written in one of several vocabularies. For each (kind,
subject) pair one vocabulary is held out: its documents never name the kind or
the subject with it, and its "paraphrase" queries use nothing else. Their words
still appear in documents of other topics, so a lexical search is drawn to the
wrong ones.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

from src.config.installation import Filtro, FiltroRangoNumerico, FiltroSeleccion
from src.ingestor.contract import DocumentoNormalizado
from src.synthetic.lexicon import ASPECTS, FAMILIES, VOCABULARIES, WORKS, Concept, Family, all_concepts
from src.text.tokens import content_tokens

# Part of every truth file and report: bump it when the output for a seed changes.
GENERATOR_VERSION = 1

GRADE_EXACT = 2
GRADE_RELATED = 1  # same kind and subject, another aspect

FIRST_DATE = date(2026, 1, 5)
ASPECTS_PER_PAIR = 4
DOCUMENTS_PER_TOPIC = 12

PROVINCES = ("Córdoba", "Córdoba", "Córdoba", "Santa Fe", "San Luis")
TOWNS = (
    "Carlos Paz", "Noetinger", "Río Cuarto", "Villa María", "San Francisco", "Alta Gracia", "Jesús María",
    "Bell Ville", "Cosquín", "La Falda", "Laboulaye", "Marcos Juárez",
)
BODIES = (
    "Ministerio de Infraestructura", "Ministerio de Educación", "Ministerio de Salud", "Ministerio de Seguridad",
    "Ministerio de Economía", "Dirección de Vialidad", "Agencia de Inversión", "Empresa de Energía",
    "Secretaría de Ambiente", "Caja de Jubilaciones", "Administración del Seguro de Salud", "Policía de la Provincia",
)
STREETS = ("Colón", "San Martín", "Belgrano", "Humberto Primo", "Figueroa Alcorta", "Santa Rosa", "Rivadavia")
SURNAMES = ("Pérez", "Gómez", "Ludueña", "Bustos", "Ferreyra", "Moyano", "Peralta", "Quiroga", "Ceballos", "Toledo")

# Sentences that any notice may carry. They say nothing about the topic.
FILLERS = (
    "Las actuaciones tramitan por Expediente Nº {file} y pueden consultarse de lunes a viernes de {h1}:00 a {h2}:00 horas.",
    "Para mayor información dirigirse a calle {street} Nº {number}, código postal {postal}.",
    "Firmado: {surname1} y {surname2}, quienes suscriben la presente a los efectos que correspondan.",
    "Los interesados deberán acreditar identidad mediante documento y constituir domicilio dentro del radio.",
    "El plazo se computará en días hábiles a partir del siguiente al de la última publicación.",
    "Consultas por correo electrónico a mesa{number}@example.org hasta el día {day} de {month}.",
    "Se hace saber a quien corresponda, bajo apercibimiento de ley.",
    "La documentación respaldatoria se encuentra agregada en el anexo que acompaña al presente aviso.",
    "Publíquese por el término de ley y archívese oportunamente.",
    "Teléfono de contacto {phone}, interno {h1}{h2}, en el horario indicado precedentemente.",
    "Todo ello de conformidad con lo establecido por la normativa vigente en la materia y sus complementarias.",
    "Quedan a disposición los antecedentes obrantes en la causa Nº {file} del año en curso.",
    "El monto consignado incluye impuesto al valor agregado y demás tributos aplicables.",
    "Intervino en lo que es de su competencia la asesoría letrada, según dictamen Nº {number}.",
)
MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
    "noviembre", "diciembre",
)
LEADS = (
    "{kind}: {subject} {aspect}.",
    "Se comunica {kind} referida a {subject}, {aspect}.",
    "{subject}. {kind}, {aspect}.",
)
MENTIONS = (
    "El presente {kind} comprende {subject}.",
    "Lo dispuesto alcanza a {subject} {aspect}.",
    "Objeto: {subject}.",
    "Corresponde a {kind} {aspect}.",
)
QUERIES = ("{kind} {subject} {aspect}", "{subject} {kind} {aspect}", "{kind} sobre {subject}, {aspect}")
DECOYS = (
    "Domicilio constituido en calle {name} Nº {number}.",
    "Interviene la firma {name} S.R.L. en calidad de tercero.",
    "Ubicado en barrio {name} de esta ciudad.",
)


@dataclass(frozen=True)
class Profile:
    key: str
    sources: tuple[str, ...]
    families: tuple[Family, ...]
    filters: tuple[Filtro, ...]


PROFILES = {
    "gazette": Profile(
        "gazette",
        ("cordoba-provincial", "carlos-paz-municipal", "noetinger-municipal"),
        FAMILIES,
        (
            FiltroSeleccion(clave="provincia", etiqueta="Provincia"),
            FiltroSeleccion(clave="municipio", etiqueta="Municipio"),
        ),
    ),
    "tenders": Profile(
        "tenders",
        ("comprar-ar-nacional", "cba-provincial-licitaciones"),
        (WORKS,),
        (
            FiltroSeleccion(clave="organismo", etiqueta="Organismo"),
            FiltroRangoNumerico(clave="monto", etiqueta="Monto estimado"),
        ),
    ),
}


@dataclass(frozen=True)
class CorpusConfig:
    seed: int = 42
    documents: int = 2000
    profile: str = "gazette"
    queries: int = 120
    subscriptions: int = 60
    republication_share: float = 0.15
    distractor_share: float = 0.10


@dataclass(frozen=True)
class Topic:
    key: str
    family: Family
    kind: Concept
    subject: Concept
    aspect: Concept

    @property
    def pair(self) -> tuple[str, str]:
        return self.kind.key, self.subject.key

    def words(self, vocabulary: int) -> dict[str, str]:
        return {
            "kind": self.kind.variants[vocabulary],
            "subject": self.subject.variants[vocabulary],
            "aspect": self.aspect.variants[vocabulary],
        }


@dataclass
class Query:
    id: str
    text: str
    kind: str  # "paraphrase" or "same_vocabulary"
    topic: str
    filters: dict[str, str]
    relevant: dict[str, int]
    concept_words: list[str] = field(default_factory=list)


@dataclass
class Subscription:
    id: str
    text: str
    filters: dict[str, str]
    must_match: list[str]


@dataclass
class Truth:
    seed: int
    profile: str
    documents: int
    generator_version: int
    queries: list[Query]
    subscriptions: list[Subscription]
    republications: list[list[str]]
    distractors: dict[str, list[str]]
    topics: dict[str, list[str]]


@dataclass
class Corpus:
    config: CorpusConfig
    profile: Profile
    documents: list[DocumentoNormalizado]
    truth: Truth

    def synonym_table(self, coverage: float = 1.0) -> dict[str, list[str]]:
        """Phrases that mean the same, for an embedding provider that has no
        model. `coverage` is the share of phrases it knows; the chosen phrases
        depend only on the seed."""
        rng = random.Random(f"synonyms:{self.config.seed}")
        phrases = [(c.key, v) for c in all_concepts() for v in c.variants]
        rng.shuffle(phrases)
        known = set(phrases[: round(len(phrases) * coverage)])
        table = {c.key: [v for v in c.variants if (c.key, v) in known] for c in all_concepts()}
        return {key: variants for key, variants in table.items() if variants}


def satisfies_filters(metadata: dict, filters: dict[str, str]) -> bool:
    """Filter semantics of the truth file, written apart from `src/search/filters.py`
    so that the engine is not checked against itself."""
    for key, wanted in filters.items():
        value = metadata.get(key)
        if value is None:
            return False
        if "," in wanted:
            low, high = wanted.split(",")
            if (low and value < float(low)) or (high and value > float(high)):
                return False
        elif value != wanted:
            return False
    return True


def _topics(rng: random.Random, profile: Profile, documents: int) -> list[Topic]:
    pairs = [(f, k, s) for f in profile.families for k in f.kinds for s in f.subjects]
    rng.shuffle(pairs)
    wanted = max(6, documents // (ASPECTS_PER_PAIR * DOCUMENTS_PER_TOPIC))
    # Beyond the last pair, a larger corpus gets more aspects instead of only more documents per topic.
    aspects = min(len(ASPECTS), max(ASPECTS_PER_PAIR, wanted * ASPECTS_PER_PAIR // len(pairs)))
    topics = []
    for family, kind, subject in pairs[:wanted]:
        for aspect in rng.sample(ASPECTS, aspects):
            key = "/".join(c.key.rsplit(".", 1)[1] for c in (kind, subject, aspect))
            topics.append(Topic(f"{family.key}/{key}", family, kind, subject, aspect))
    return topics


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


class _Writer:
    def __init__(self, config: CorpusConfig, profile: Profile, held_out: dict[tuple[str, str], int]) -> None:
        self._config = config
        self._profile = profile
        self._held_out = held_out

    def _slots(self, rng: random.Random) -> dict[str, object]:
        return {
            "file": f"{rng.randrange(1, 999):04d}-{rng.randrange(10**5, 10**6)}/2026",
            "h1": rng.randrange(7, 10),
            "h2": rng.randrange(12, 19),
            "street": rng.choice(STREETS),
            "number": rng.randrange(10, 5000),
            "postal": rng.randrange(5000, 6000),
            "surname1": rng.choice(SURNAMES),
            "surname2": rng.choice(SURNAMES),
            "day": rng.randrange(1, 29),
            "month": rng.choice(MONTHS),
            "phone": f"351-{rng.randrange(4_000_000, 5_000_000)}",
        }

    def metadata(self, rng: random.Random) -> dict:
        if self._profile.key == "tenders":
            # Integer arithmetic only: the same amount on every machine.
            return {"organismo": rng.choice(BODIES), "monto": float(rng.randrange(1000, 10_000) * 10 ** rng.randrange(2, 6))}
        metadata = {"provincia": rng.choice(PROVINCES)}
        if rng.random() < 0.7:
            metadata["municipio"] = rng.choice(TOWNS)
        return metadata

    def body(self, rng: random.Random, topic: Topic, decoy: str | None) -> str:
        choices = [v for v in range(VOCABULARIES) if v != self._held_out[topic.pair]]
        words = topic.words(rng.choice(choices))
        # The aspect is not held out: it gives lexical search a weak, real signal.
        words["aspect"] = rng.choice(topic.aspect.variants)
        sentences = [_capitalize(rng.choice(LEADS).format(**words))]
        fillers = [f.format(**self._slots(rng)) for f in rng.sample(FILLERS, rng.randrange(2, 10))]
        extras = [m.format(**words) for m in rng.sample(MENTIONS, 2)]
        if decoy:
            extras.append(rng.choice(DECOYS).format(name=decoy.title(), number=rng.randrange(10, 5000)))
        rest = fillers + extras
        rng.shuffle(rest)
        return f"{rng.choice(BODIES).upper()}\n" + " ".join([*sentences, *rest])


def generate_corpus(config: CorpusConfig) -> Corpus:
    if config.profile not in PROFILES:
        raise ValueError(f"unknown profile {config.profile!r}; choose one of {', '.join(PROFILES)}")
    if config.documents < 100:
        raise ValueError("documents must be at least 100, or most topics would have none")

    profile = PROFILES[config.profile]
    # One generator per purpose, seeded by name, so that adding a query does not change the documents.
    setup = random.Random(f"{config.seed}:{config.profile}:setup")
    rng = random.Random(f"{config.seed}:{config.profile}:documents")

    topics = _topics(setup, profile, config.documents)
    held_out = {topic.pair: setup.randrange(VOCABULARIES) for topic in topics}
    drafts = _draft_queries(setup, config, topics, held_out)
    writer = _Writer(config, profile, held_out)

    documents: list[DocumentoNormalizado] = []
    members: dict[str, list[int]] = {t.key: [] for t in topics}
    republications: list[list[str]] = []
    decoyed: dict[int, list[int]] = {}
    notices = 0

    while len(documents) < config.documents:
        position = len(documents)
        # The first documents walk the topic list, so that every topic has at least one.
        topic = topics[notices] if notices < len(topics) else rng.choice(topics)
        notices += 1
        decoy = None
        if rng.random() < config.distractor_share:
            draft_index = rng.randrange(len(drafts))
            draft = drafts[draft_index]
            if draft.topic.pair != topic.pair:
                decoy = draft.topic.subject.variants[draft.vocabulary]
        body = writer.body(rng, topic, decoy)
        metadata = writer.metadata(rng)
        published = FIRST_DATE + timedelta(days=rng.randrange(250))
        source = rng.choice(profile.sources)

        copies = 1
        if rng.random() < config.republication_share:
            copies += rng.randrange(1, 3)
        copies = min(copies, config.documents - position)

        group = []
        for copy in range(copies):
            index = len(documents)
            when = published + timedelta(days=copy)
            identifier = f"SYN-{config.profile}-{index:07d}"
            notice = 600_000 + index
            documents.append(
                DocumentoNormalizado(
                    fuente_clave=source,
                    identificador_externo=identifier,
                    fecha=when,
                    texto=f"{body}\nAviso Nº {notice} - {when.day}/{when.month}/{when.year}.",
                    url_fuente=f"https://example.org/{config.profile}/{identifier}",
                    titulo=_capitalize(f"{topic.kind.variants[0]} Nº {notice}"),
                    metadata=dict(metadata),
                )
            )
            members[topic.key].append(index)
            group.append(identifier)
            if decoy:
                decoyed.setdefault(draft_index, []).append(index)
        if copies > 1:
            republications.append(group)

    truth = _build_truth(config, profile, topics, drafts, documents, members, republications, decoyed)
    return Corpus(config, profile, documents, truth)


@dataclass(frozen=True)
class _Draft:
    topic: Topic
    vocabulary: int
    kind: str
    text: str


def _draft_queries(
    rng: random.Random, config: CorpusConfig, topics: list[Topic], held_out: dict[tuple[str, str], int]
) -> list[_Draft]:
    drafts = []
    for i in range(config.queries):
        topic = rng.choice(topics)
        hidden = held_out[topic.pair]
        if i % 2 == 0:
            kind, vocabulary = "paraphrase", hidden
        else:
            kind, vocabulary = "same_vocabulary", rng.choice([v for v in range(VOCABULARIES) if v != hidden])
        drafts.append(_Draft(topic, vocabulary, kind, rng.choice(QUERIES).format(**topic.words(vocabulary))))
    return drafts


def _filters_for(rng: random.Random, profile: Profile, candidates: list[DocumentoNormalizado]) -> dict[str, str]:
    """A filter that keeps at least one of the candidates: its value comes from one of them."""
    document = rng.choice(candidates)
    available = [f for f in profile.filters if f.clave in document.metadata]
    chosen = rng.choice(available)
    value = document.metadata[chosen.clave]
    if isinstance(chosen, FiltroRangoNumerico):
        bounds = (f"{value / 4:.2f},{value * 4:.2f}", f"{value / 2:.2f},", f",{value * 2:.2f}")
        return {chosen.clave: rng.choice(bounds)}
    return {chosen.clave: value}


def _build_truth(
    config: CorpusConfig,
    profile: Profile,
    topics: list[Topic],
    drafts: list[_Draft],
    documents: list[DocumentoNormalizado],
    members: dict[str, list[int]],
    republications: list[list[str]],
    decoyed: dict[int, list[int]],
) -> Truth:
    rng = random.Random(f"{config.seed}:{config.profile}:truth")
    siblings: dict[tuple[str, str], list[Topic]] = {}
    for topic in topics:
        siblings.setdefault(topic.pair, []).append(topic)

    def matching(indices: list[int], filters: dict[str, str]) -> list[str]:
        return [documents[i].identificador_externo for i in indices if satisfies_filters(documents[i].metadata, filters)]

    queries, distractors = [], {}
    for i, draft in enumerate(drafts):
        exact = members[draft.topic.key]
        filters = _filters_for(rng, profile, [documents[j] for j in exact]) if rng.random() < 0.3 else {}
        relevant = dict.fromkeys(matching(exact, filters), GRADE_EXACT)
        for sibling in siblings[draft.topic.pair]:
            if sibling.key != draft.topic.key:
                relevant.update(dict.fromkeys(matching(members[sibling.key], filters), GRADE_RELATED))
        identifier = f"q{i:04d}"
        words = sorted({w for phrase in draft.topic.words(draft.vocabulary).values() for w in content_tokens(phrase)})
        queries.append(Query(identifier, draft.text, draft.kind, draft.topic.key, filters, relevant, words))
        if i in decoyed:
            distractors[identifier] = [documents[j].identificador_externo for j in decoyed[i]]

    subscriptions = []
    for i in range(config.subscriptions):
        topic = rng.choice(topics)
        exact = members[topic.key]
        filters = _filters_for(rng, profile, [documents[j] for j in exact]) if rng.random() < 0.5 else {}
        text = rng.choice(QUERIES).format(**topic.words(rng.randrange(VOCABULARIES)))
        subscriptions.append(Subscription(f"s{i:04d}", text, filters, matching(exact, filters)))

    return Truth(
        seed=config.seed,
        profile=config.profile,
        documents=len(documents),
        generator_version=GENERATOR_VERSION,
        queries=queries,
        subscriptions=subscriptions,
        republications=republications,
        distractors=distractors,
        topics={key: [documents[i].identificador_externo for i in ids] for key, ids in sorted(members.items())},
    )


def _json(value: object, **options) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, **options)


def write_corpus(corpus: Corpus, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "documents.jsonl").open("w", encoding="utf-8", newline="\n") as out:
        for document in corpus.documents:
            record = {
                "fuente_clave": document.fuente_clave,
                "identificador_externo": document.identificador_externo,
                "fecha": document.fecha.isoformat(),
                "titulo": document.titulo,
                "texto": document.texto,
                "url_fuente": document.url_fuente,
                "metadata": document.metadata,
            }
            out.write(_json(record) + "\n")
    (directory / "truth.json").write_text(_json(asdict(corpus.truth), indent=1) + "\n", encoding="utf-8", newline="\n")
    (directory / "synonyms.json").write_text(
        _json(corpus.synonym_table(), indent=1) + "\n", encoding="utf-8", newline="\n"
    )
