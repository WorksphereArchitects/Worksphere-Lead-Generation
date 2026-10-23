import re
from functools import lru_cache



# ============================================================
# CONFIGURATION
# ============================================================

MIN_EXCERPT_LENGTH = 50
MIN_WORD_COUNT = 8

SEMANTIC_VALIDATION_THRESHOLD = 0.30

MAX_VALIDATION_SCORE = 100


# ============================================================
# VALID EVIDENCE TYPES
# ============================================================

VALID_EVIDENCE_TYPES = {

    "investment",
    "capacity_expansion",
    "facility_expansion",
    "new_facility",
    "facility_construction",
    "plant_commissioning",

    "land_acquisition",
    "land_development",
    "warehouse_distribution",
    "office_expansion",
    "geographic_expansion",

    "hiring",
    "workforce_reduction",

    "leadership_change",

    "acquisition",
    "merger",

    "technology_transformation",
    "sustainability",
}


# ============================================================
# SEMANTIC DEFINITIONS
# ============================================================

EVIDENCE_DEFINITIONS = {

    "investment":
        "Actual company investment, capital expenditure, "
        "capital allocation, funding, or material financial "
        "commitment toward a business activity or project.",

    "capacity_expansion":
        "An increase in manufacturing, production, operational, "
        "installed, processing, storage, or business capacity.",

    "facility_expansion":
        "Expansion, development, upgrade, or enlargement of "
        "an existing plant, factory, manufacturing facility, "
        "office, warehouse, campus, or operational facility.",

    "new_facility":
        "Establishment, construction, development, opening, "
        "or planned creation of a new plant, factory, office, "
        "warehouse, campus, headquarters, or operational site.",

    "facility_construction":
        "Construction or physical development of a plant, "
        "factory, manufacturing facility, office, warehouse, "
        "campus, or other business facility.",

    "plant_commissioning":
        "Commissioning, commercial production, startup, or "
        "commencement of operations at a new or expanded plant.",

    "land_acquisition":
        "Purchase or acquisition of land by a company for "
        "business development, operations, expansion, or a "
        "future physical project.",

    "land_development":
        "Planned, proposed, or pending development of existing land "
        "for a future business, industrial, commercial, facility, "
        "or operational project. This includes land development "
        "awaiting government or regulatory approval, but does not "
        "mean land acquisition and does not imply construction has begun.",

    "warehouse_distribution":
        "Development, opening, acquisition, or expansion of "
        "warehouse, logistics, distribution, or supply-chain "
        "infrastructure.",

    "office_expansion":
        "Opening, development, relocation, acquisition, or "
        "expansion of offices, headquarters, corporate campuses, "
        "or workplace facilities.",

    "geographic_expansion":
        "Expansion into a new geographic region, city, state, "
        "country, market, or operating location.",

    "hiring":
        "Material recruitment, hiring, workforce growth, "
        "employee expansion, or increase in headcount.",

    "workforce_reduction":
        "Layoffs, employee reductions, headcount reductions, "
        "downsizing, workforce restructuring, or job cuts.",

    "leadership_change":
        "Actual appointment, resignation, retirement, replacement, "
        "or reappointment involving a senior executive or board "
        "leader such as CEO, CFO, COO, CTO, CHRO, managing "
        "director, executive director, or president.",

    "acquisition":
        "Acquisition, takeover, purchase, or agreed acquisition "
        "of another company, business, asset, or operating entity.",

    "merger":
        "Merger, amalgamation, demerger, scheme of arrangement, "
        "or other corporate combination between companies.",

    "technology_transformation":
        "Material digital transformation, automation, artificial "
        "intelligence, machine learning, technology modernization, "
        "or implementation of major technology infrastructure.",

    "sustainability":
        "Material sustainability, renewable energy, net-zero, "
        "decarbonization, emissions reduction, clean energy, "
        "or environmental infrastructure initiative.",
}


# ============================================================
# MODELS
# ============================================================

@lru_cache(maxsize=1)
def get_spacy_model():

    # Keep spaCy's native extensions out of the Flask startup import path.
    import spacy

    return spacy.load(
        "en_core_web_sm",
        disable=["ner"]
    )


@lru_cache(maxsize=1)
def get_embedding_model():

    # Import lazily so a blocked/broken SciPy native DLL does not prevent
    # Flask and unrelated API routes from starting.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        "all-MiniLM-L6-v2"
    )


# ============================================================
# BASIC NORMALIZATION
# ============================================================

def normalize(text):

    if not text:
        return ""

    return re.sub(
        r"\s+",
        " ",
        text.lower()
    ).strip()


def _trace_normalize(text):
    """Normalize PDF/LLM formatting differences without changing the words.

    This is deliberately stricter than fuzzy matching: it only removes
    formatting noise commonly introduced by PDF extraction or Gemini output.
    """
    if not text:
        return ""

    text = str(text)

    # Unicode compatibility normalization (e.g. full-width characters).
    import unicodedata
    text = unicodedata.normalize("NFKC", text)

    # Normalize common PDF/LLM punctuation variants.
    text = (
        text.replace("\u2018", "'")
            .replace("\u2019", "'")
            .replace("\u201c", '"')
            .replace("\u201d", '"')
            .replace("\u2013", "-")
            .replace("\u2014", "-")
            .replace("\u2212", "-")
            .replace("\u00a0", " ")
    )

    # PDF extraction frequently breaks a word at a line boundary as
    # ``manu-\nfacturing``. Rejoin that word before whitespace normalization.
    text = re.sub(r"(?<=\w)-\s+(?=\w)", "", text)

    # Collapse all whitespace differences.
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _trace_compact(text):
    """Remove formatting punctuation so harmless PDF punctuation differences
    do not break otherwise exact word traceability.
    """
    normalized = _trace_normalize(text)
    return re.sub(r"[^a-z0-9]+", "", normalized)


def _ellipsis_parts(excerpt):
    """Return meaningful parts when Gemini uses an ellipsis to shorten a quote."""
    normalized = _trace_normalize(excerpt)
    # Support both three dots and the single Unicode ellipsis character.
    parts = re.split(r"(?:\.{3}|…)", normalized)
    return [part.strip() for part in parts if part.strip()]


def excerpt_exists_in_document(
    excerpt,
    document_text
):
    """Check whether an LLM excerpt is traceable to the raw source.

    Matching is deterministic and intentionally does NOT use semantic/fuzzy
    similarity. It supports only three common presentation differences:

    1. whitespace/newline differences,
    2. PDF punctuation/Unicode normalization, and
    3. Gemini inserting ``...`` to omit a middle portion of a source quote.

    For ellipsis excerpts, every quoted segment must occur in the source in
    the same order. This prevents an LLM from inventing the quoted words.
    """
    if not excerpt or not document_text:
        return False

    normalized_excerpt = _trace_normalize(excerpt)
    normalized_document = _trace_normalize(document_text)

    # First choice: exact normalized substring. This is the strongest check.
    if normalized_excerpt in normalized_document:
        return True

    # Second choice: punctuation/whitespace-insensitive exact substring.
    compact_excerpt = _trace_compact(excerpt)
    compact_document = _trace_compact(document_text)
    if compact_excerpt and compact_excerpt in compact_document:
        return True

    # Third choice: Gemini may shorten a long source quote with an ellipsis.
    # Require every retained segment to be substantial and ordered.
    parts = _ellipsis_parts(excerpt)
    if len(parts) < 2:
        return False

    position = 0
    matched_parts = 0
    for part in parts:
        compact_part = _trace_compact(part)
        # Do not allow an ellipsis check to succeed on tiny fragments such as
        # a number or a single common word.
        if len(compact_part) < 20:
            return False

        found = compact_document.find(compact_part, position)
        if found == -1:
            return False

        position = found + len(compact_part)
        matched_parts += 1

    return matched_parts == len(parts)


# ============================================================
# NEGATIVE / BOILERPLATE CONTEXT
# ============================================================

GENERIC_NEGATIVE_CONTEXTS = [

    "auditor",
    "auditors",
    "audit committee",
    "proxy",
    "proxies",

    "shareholder",
    "shareholders",

    "remuneration",

    "corporate governance",
    "governance",

    "financial statements",

    "dividend",

    "compliance",

    "secretarial",

    "legal proceeding",
    "litigation",

    "accounting policy",
    "accounting policies",

    "terms of reference",

    "criteria for selection",
    "criteria for appointment",

    "process for appointment",

    "policy",
]


def get_negative_contexts(text):

    normalized = normalize(
        text
    )

    return [
        context
        for context in GENERIC_NEGATIVE_CONTEXTS
        if context in normalized
    ]


# ============================================================
# EVENT / ACTION LANGUAGE
# ============================================================

ACTION_TERMS = {

    "invest",
    "invested",
    "investment",
    "investing",

    "allocate",
    "allocated",

    "expand",
    "expanded",
    "expansion",

    "increase",
    "increased",

    "build",
    "built",

    "construct",
    "constructed",
    "construction",

    "develop",
    "developed",
    "development",

    "establish",
    "established",
    "establishment",

    "commission",
    "commissioned",

    "acquire",
    "acquired",
    "acquisition",

    "purchase",
    "purchased",

    "launch",
    "launched",

    "open",
    "opened",

    "install",
    "installed",

    "upgrade",
    "upgraded",

    "hire",
    "hired",
    "hiring",

    "recruit",
    "recruited",
    "recruitment",

    "appoint",
    "appointed",
    "appointment",

    "resign",
    "resigned",
    "resignation",

    "retire",
    "retired",
    "retirement",

    "acquire",
    "acquired",

    "merge",
    "merged",

    "implement",
    "implemented",

    "renew",
    "renewed",

    "develop",
    "development",
}


FUTURE_TERMS = {

    "will",
    "plan",
    "plans",
    "planned",
    "planning",

    "propose",
    "proposed",

    "proposes",

    "expect",
    "expected",
    "expects",

    "intend",
    "intends",
    "intended",

    "target",
    "targeted",

    "future",
    "upcoming",

    "envisaged",
}


PENDING_TERMS = {

    "pending",
    "awaiting",
    "approval",

    "subject to approval",
    "subject to approvals",

    "awaiting approval",
    "awaiting finalization",

    "government approval",
    "regulatory approval",

    "yet to be approved",
}


ACTUAL_EVENT_TERMS = {

    "completed",
    "commissioned",
    "opened",
    "launched",

    "acquired",
    "appointed",
    "reappointed",

    "resigned",
    "retired",

    "constructed",
    "installed",

    "started",
    "commenced",

    "implemented",
    "established",

    "renewed",
}


# ============================================================
# STATE CLASSIFICATION
# ============================================================

def _normalize_event_state(value):

    if not value:
        return None

    value = normalize(str(value))

    aliases = {
        "actual": "actual",
        "completed": "completed",
        "commissioned": "commissioned",
        "ongoing": "ongoing",
        "in progress": "ongoing",
        "under construction": "under_construction",
        "under_construction": "under_construction",
        "planned": "planned",
        "proposed": "proposed",
        "pending": "pending",
        "awaiting approval": "awaiting_approval",
        "awaiting_approval": "awaiting_approval",
        "approved": "approved",
        "negative": "negative",
        "context": "context",
    }

    return aliases.get(value, value)


def _sentence_state_signals(text):
    """Return state evidence by sentence/phrase, not whole-document keyword precedence."""

    normalized = normalize(text)

    negative_patterns = [
        r"\bthere (?:is|are) no change(?:s)?\b",
        r"\bno new (?:project|facility|technology|investment|development)\b",
        r"\bno (?:change|changes)\b",
        r"\bhas not (?:commenced|started|begun)\b",
        r"\bhas yet to (?:commence|start|begin)\b",
        r"\bnot commenced\b",
        r"\bnot started\b",
    ]
    if any(re.search(p, normalized) for p in negative_patterns):
        return "negative"

    # Explicit actual-event constructions have highest precedence.
    actual_patterns = [
        r"\bwas commissioned\b",
        r"\bwere commissioned\b",
        r"\bhas been commissioned\b",
        r"\bhave been commissioned\b",
        r"\bsuccessfully commissioned\b",
        r"\bwas acquired\b",
        r"\bwere acquired\b",
        r"\bhas been acquired\b",
        r"\bwas appointed\b",
        r"\bwere appointed\b",
        r"\bhas been appointed\b",
        r"\bwas approved\b",
        r"\bwere approved\b",
        r"\bwas amalgamated\b",
        r"\bwere amalgamated\b",
        r"\bbecame effective\b",
        r"\bcompleted\b",
        r"\bcommenced commercial production\b",
        r"\bcommercial production (?:has )?commenced\b",
        r"\boperations have commenced\b",
        r"\boperations commenced\b",
        r"\bconstruction (?:has )?commenced\b",
        r"\bconstruction started\b",
        r"\bconstruction completed\b",
        r"\binstalled and commissioned\b",
        r"\brenewed\b",
        r"\blaunched\b",
        r"\bopened\b",
    ]
    if any(re.search(p, normalized) for p in actual_patterns):
        return "actual"

    # Explicit ongoing/construction language.
    ongoing_patterns = [
        r"\bunder construction\b",
        r"\bconstruction is ongoing\b",
        r"\bconstruction work is ongoing\b",
        r"\bproject is progressing\b",
        r"\bproject is progressing well\b",
        r"\bconstruction is progressing\b",
        r"\bcurrently under development\b",
        r"\bwork is in progress\b",
        r"\bbeing developed\b",
        r"\bbeing constructed\b",
        r"\bongoing expansion\b",
        r"\bexpansion is ongoing\b",
    ]
    if any(re.search(p, normalized) for p in ongoing_patterns):
        return "ongoing"

    approval_patterns = [
        r"\bawaiting (?:finalization|approval|approvals)\b",
        r"\bsubject to (?:final|government|regulatory)? ?approval\b",
        r"\bpending approval\b",
        r"\bapproval is pending\b",
    ]
    if any(re.search(p, normalized) for p in approval_patterns):
        return "awaiting_approval"

    future_patterns = [
        r"\bproposed\b",
        r"\bproposes? to\b",
        r"\bplans? to\b",
        r"\bplanned\b",
        r"\bwill (?:be|commence|start|begin|set up|construct|develop)\b",
        r"\bwould commence\b",
        r"\bintends? to\b",
        r"\bexpected to\b",
        r"\btarget(?:ed)?\b",
        r"\benvisaged\b",
        r"\binitiated the process for setting up\b",
        r"\bprocess for setting up\b",
    ]
    if any(re.search(p, normalized) for p in future_patterns):
        return "planned"

    return "context"


def classify_event_state(text, supplied_state=None):
    """Resolve event state while preserving an explicit Gemini state.

    The validator must not silently reclassify a state that Gemini supplied.
    Gemini is responsible for interpreting the event state; the validator
    verifies traceability and event-type support. State inference is used only
    when Gemini did not provide a state.
    """

    supplied = _normalize_event_state(supplied_state)

    # An explicit model state is authoritative for reporting.
    # In particular, keep states such as completed, commissioned, approved,
    # planned, proposed, awaiting_approval, and context exactly as normalized.
    if supplied:
        return supplied

    return _sentence_state_signals(text)


# ============================================================
# LEADERSHIP VALIDATION
# ============================================================

LEADERSHIP_ROLES = [

    "ceo",
    "cfo",
    "coo",
    "cto",
    "chro",

    "chief executive",
    "chief financial",
    "chief operating",
    "chief technology",
    "chief human resources",

    "managing director",
    "executive director",

    "whole-time director",
    "whole time director",

    "independent director",
    "non-executive director",
    "non executive director",

    "president",
    "chairman",
    "chairperson",
]


LEADERSHIP_ACTIONS = [

    "appointed",
    "appointment",

    "reappointed",
    "reappointment",

    "resigned",
    "resignation",

    "retired",
    "retirement",

    "replaced",
    "replacement",

    "ceased",
    "ceasing",

    "joined",
]


def validate_leadership_context(
    excerpt
):

    normalized = normalize(
        excerpt
    )

    has_role = any(
        role in normalized
        for role in LEADERSHIP_ROLES
    )

    has_action = any(
        action in normalized
        for action in LEADERSHIP_ACTIONS
    )

    # Both are required.
    if not has_role:
        return False

    if not has_action:
        return False

    # Reject policy/governance descriptions.
    policy_patterns = [

        "criteria for appointment",
        "criteria for selection",

        "process for appointment",
        "process of appointment",

        "terms of reference",

        "policy for appointment",

        "selection criteria",
    ]

    if any(
        pattern in normalized
        for pattern in policy_patterns
    ):
        return False

    return True


# ============================================================
# PHYSICAL / BUSINESS CONSEQUENCE VALIDATION
# ============================================================

PHYSICAL_TERMS = [

    "land",
    "acre",
    "acres",

    "site",
    "facility",

    "plant",
    "factory",

    "manufacturing unit",
    "manufacturing facility",

    "warehouse",

    "distribution centre",
    "distribution center",

    "office",
    "headquarters",

    "campus",

    "building",

    "property",

    "production block",

    "laboratory",
    "lab",

    "research centre",
    "research center",

    "infrastructure",
]


PHYSICAL_ACTIONS = [

    "develop",
    "development",

    "construct",
    "construction",

    "build",
    "building",

    "expand",
    "expansion",

    "establish",
    "established",

    "commission",
    "commissioned",

    "acquire",
    "acquired",

    "purchase",
    "purchased",

    "install",
    "installed",

    "upgrade",
    "upgraded",

    "open",
    "opened",
]


def has_physical_consequence(
    excerpt
):

    normalized = normalize(
        excerpt
    )

    physical = any(
        term in normalized
        for term in PHYSICAL_TERMS
    )

    action = any(
        term in normalized
        for term in PHYSICAL_ACTIONS
    )

    return physical and action


# ============================================================
# MONEY / SCALE / QUANTITY VALIDATION
# ============================================================

def has_material_scale(
    excerpt
):

    normalized = normalize(
        excerpt
    )

    money_pattern = (
        r"(₹|rs\.?|inr|\$|€|£)"
        r"\s*[\d,.]+"
    )

    measurement_pattern = (
        r"\b\d+(?:\.\d+)?\s*"
        r"(?:acre|acres|"
        r"sq\.?\s*ft|sqft|"
        r"square feet|"
        r"hectare|hectares|"
        r"mw|gw|"
        r"mt|tonnes?|tons?|"
        r"employees?|"
        r"production blocks?)\b"
    )

    if re.search(
        money_pattern,
        normalized,
        re.IGNORECASE
    ):
        return True

    if re.search(
        measurement_pattern,
        normalized,
        re.IGNORECASE
    ):
        return True

    return False


# ============================================================
# SPACY LINGUISTIC VALIDATION
# ============================================================

def linguistic_validation(
    excerpt,
    evidence_type
):

    nlp = get_spacy_model()

    doc = nlp(
        excerpt
    )

    lemmas = {

        token.lemma_.lower()

        for token in doc

        if token.is_alpha

        and not token.is_stop
    }

    score = 0

    reasons = []

    # --------------------------------------------------------
    # ACTION LANGUAGE
    # --------------------------------------------------------

    matched_actions = (
        lemmas.intersection(
            ACTION_TERMS
        )
    )

    if matched_actions:

        score += 15

        reasons.append(
            "business action language detected: "
            + ", ".join(
                sorted(
                    list(
                        matched_actions
                    )
                )[:5]
            )
        )

    # --------------------------------------------------------
    # FUTURE / PLANNING LANGUAGE
    # --------------------------------------------------------

    matched_future = (
        lemmas.intersection(
            FUTURE_TERMS
        )
    )

    if matched_future:

        score += 10

        reasons.append(
            "future/planning language detected"
        )

    # --------------------------------------------------------
    # PENDING / APPROVAL
    # --------------------------------------------------------

    normalized = normalize(
        excerpt
    )

    matched_pending = [
        term
        for term in PENDING_TERMS
        if term in normalized
    ]

    if matched_pending:

        score += 12

        reasons.append(
            "pending/approval language detected"
        )

    # --------------------------------------------------------
    # ACTUAL EVENT
    # --------------------------------------------------------

    matched_actual = [
        term
        for term in ACTUAL_EVENT_TERMS
        if term in normalized
    ]

    if matched_actual:

        score += 8

        reasons.append(
            "actual event language detected"
        )

    # --------------------------------------------------------
    # PHYSICAL CONSEQUENCE
    # --------------------------------------------------------

    if has_physical_consequence(
        excerpt
    ):

        score += 15

        reasons.append(
            "physical/business consequence detected"
        )

    # --------------------------------------------------------
    # MATERIAL SCALE
    # --------------------------------------------------------

    if has_material_scale(
        excerpt
    ):

        score += 10

        reasons.append(
            "material scale or measurement detected"
        )

    # --------------------------------------------------------
    # LEADERSHIP
    # --------------------------------------------------------

    if evidence_type == "leadership_change":

        if validate_leadership_context(
            excerpt
        ):

            score += 25

            reasons.append(
                "senior leadership role and action detected"
            )

        else:

            score -= 40

            reasons.append(
                "no valid senior leadership event detected"
            )

    # --------------------------------------------------------
    # NEGATIVE CONTEXT
    # --------------------------------------------------------

    negative = get_negative_contexts(
        excerpt
    )

    if negative:

        score -= min(
            40,
            len(negative) * 10
        )

        reasons.append(
            "negative/governance context detected: "
            + ", ".join(
                negative[:5]
            )
        )

    return score, reasons


# ============================================================
# SEMANTIC VALIDATION
# ============================================================

def semantic_validation(
    excerpt,
    evidence_type
):

    model = get_embedding_model()

    definition = (
        EVIDENCE_DEFINITIONS.get(
            evidence_type
        )
    )

    if not definition:

        return (
            -30,
            0.0,
            ["unknown evidence type"]
        )

    excerpt_embedding = model.encode(
        excerpt,
        convert_to_tensor=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    definition_embedding = model.encode(
        definition,
        convert_to_tensor=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    from sentence_transformers import util

    similarity = float(
        util.cos_sim(
            excerpt_embedding,
            definition_embedding
        )[0][0]
    )

    score = 0
    reasons = []

    if similarity >= 0.55:

        score = 45

        reasons.append(
            "very strong semantic match"
        )

    elif similarity >= 0.45:

        score = 35

        reasons.append(
            "strong semantic match"
        )

    elif similarity >= 0.40:

        score = 28

        reasons.append(
            "good semantic match"
        )

    elif similarity >= SEMANTIC_VALIDATION_THRESHOLD:

        score = 18

        reasons.append(
            "acceptable semantic match"
        )

    else:

        score = -25

        reasons.append(
            "weak semantic match"
        )

    return (
        score,
        similarity,
        reasons
    )


# ============================================================
# NEGATIVE EVIDENCE VALIDATION
# ============================================================

EXPLICIT_NEGATIVE_PATTERNS = [
    r"\bthere is no (?:change|increase|decrease|addition|new)\b",
    r"\bthere are no (?:changes|increases|decreases|additions)\b",
    r"\bno new\b",
    r"\bno change\b",
    r"\bno changes\b",
    r"\bnone\b",
    r"\bnil\b",
    r"\bnot commenced\b",
    r"\bnot started\b",
    r"\bhas not\b",
    r"\bhave not\b",
    r"\bwas not\b",
    r"\bwere not\b",
    r"\bdid not\b",
    r"\bdoes not\b",
    r"\bdo not\b",
    r"\bno plans?\b",
    r"\bno proposal\b",
    r"\bno proposed\b",
    r"\bnot undertaken\b",
    r"\bnot imported\b",
    r"\bnot acquired\b",
    r"\bnot appointed\b",
    r"\bno appointment\b",
]

NEGATIVE_TOPIC_PATTERNS = {
    "leadership": [
        "senior management", "senior leadership", "management",
        "key managerial personnel", "director", "directors",
        "chief executive", "managing director", "executive director",
    ],
    "technology": [
        "new technology", "technology", "technologies", "imported",
        "digital transformation", "automation", "software", "erp",
    ],
    "facility": [
        "facility", "plant", "factory", "warehouse", "office",
        "construction", "development", "capacity", "expansion",
    ],
    "acquisition": [
        "acquisition", "acquired", "purchase", "purchased", "land",
        "property",
    ],
    "workforce": [
        "employees", "employee", "headcount", "workforce", "hiring",
        "recruitment", "layoff", "redundancy",
    ],
}

GENERIC_NEGATIVE_ONLY_PATTERNS = [
    "there were no",
    "no material",
    "no significant",
    "not applicable",
    "not required",
    "not mandatory",
]


def _get_field(obj, *names):
    """Read a field from either a dict or a normal object."""
    if obj is None:
        return None
    for name in names:
        if isinstance(obj, dict):
            value = obj.get(name)
        else:
            value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


def _negative_claim_text(evidence):
    """Extract the model's negative claim/statement from common schemas."""
    return _get_field(
        evidence,
        "claim",
        "statement",
        "description",
        "reason",
        "text",
        "negative_statement",
        "evidence",
    ) or ""


def _negative_topic(claim, excerpt):
    """Infer the business topic of a negative statement."""
    text = normalize(f"{claim} {excerpt}")
    matches = []
    for topic, terms in NEGATIVE_TOPIC_PATTERNS.items():
        if any(term in text for term in terms):
            matches.append(topic)
    return matches


def validate_negative_evidence(evidence, document):
    """
    Validate Gemini's negative-evidence items.

    This is intentionally separate from validate_evidence(), because
    negative evidence is not a positive opportunity signal. It still
    requires exact source traceability, an explicit negative statement,
    a meaningful business topic, and direct support for the model claim.
    """
    if not document:
        return {
            "status": "rejected",
            "reason": "Source document does not exist.",
        }

    if not getattr(document, "raw_text", None):
        return {
            "status": "rejected",
            "reason": "Source document does not contain raw text.",
        }

    excerpt = (_get_field(evidence, "excerpt", "evidence_excerpt") or "").strip()
    claim = _negative_claim_text(evidence).strip()

    if not excerpt:
        return {
            "status": "rejected",
            "reason": "Negative evidence excerpt is empty.",
        }

    if len(excerpt) < MIN_EXCERPT_LENGTH:
        return {
            "status": "rejected",
            "reason": "Negative evidence excerpt is too short.",
        }

    if len(excerpt.split()) < MIN_WORD_COUNT:
        return {
            "status": "rejected",
            "reason": "Negative evidence excerpt contains too few words.",
        }

    if not excerpt_exists_in_document(excerpt, document.raw_text):
        return {
            "status": "rejected",
            "reason": "Negative evidence excerpt was not found in the source document.",
        }

    normalized_excerpt = normalize(excerpt)
    normalized_claim = normalize(claim)

    # A negative item must contain an explicit negative construction.
    explicit_negative = any(
        re.search(pattern, normalized_excerpt)
        for pattern in EXPLICIT_NEGATIVE_PATTERNS
    )
    if not explicit_negative:
        return {
            "status": "rejected",
            "reason": (
                "Excerpt does not contain an explicit negative/no-change "
                "statement; negative evidence cannot be inferred from "
                "tables, lists, names, or absence of an action."
            ),
        }

    # Reject generic administrative/governance boilerplate.
    generic_only = any(
        pattern in normalized_excerpt
        for pattern in GENERIC_NEGATIVE_ONLY_PATTERNS
    )
    if generic_only and not _negative_topic(claim, excerpt):
        return {
            "status": "rejected",
            "reason": "Negative statement is generic boilerplate without a meaningful business topic.",
        }

    topics = _negative_topic(claim, excerpt)
    if not topics:
        return {
            "status": "rejected",
            "reason": (
                "Negative statement does not identify a meaningful "
                "WorkSphere-relevant business topic."
            ),
        }

    # If Gemini supplied a claim, require the excerpt to directly support it.
    # Exact excerpt traceability alone is not enough: the excerpt must
    # actually express the claimed negative condition.
    if claim:
        claim_words = [
            word for word in re.findall(r"[a-z0-9]+", normalized_claim)
            if len(word) >= 4
        ]
        # Ignore generic reasoning words and compare meaningful claim terms.
        ignored = {
            "there", "were", "have", "has", "been", "that", "this",
            "with", "from", "does", "not", "last", "years", "year",
            "company", "report", "evidence", "statement",
        }
        meaningful = [w for w in claim_words if w not in ignored]

        if meaningful:
            overlap = sum(
                1 for word in set(meaningful)
                if word in normalized_excerpt
            ) / len(set(meaningful))

            if overlap < 0.45:
                return {
                    "status": "rejected",
                    "reason": (
                        "Negative evidence claim is not directly supported "
                        "by the supplied source excerpt."
                    ),
                    "claim_excerpt_overlap": round(overlap, 4),
                }

    # Negative evidence is useful only when it represents an actual
    # explicit disclosure, not a paragraph that happens to contain
    # a negative word while discussing an unrelated topic.
    if any(
        phrase in normalized_excerpt
        for phrase in [
            "key managerial personnel",
            "names of directors",
            "list of directors",
        ]
    ) and not any(
        phrase in normalized_excerpt
        for phrase in [
            "no change",
            "no changes",
            "unchanged",
            "no appointment",
            "no new appointment",
        ]
    ):
        return {
            "status": "rejected",
            "reason": (
                "Leadership names/designations are present, but the excerpt "
                "does not explicitly state a no-change leadership condition."
            ),
        }

    return {
        "status": "validated",
        "reason": (
            "Negative evidence is explicitly stated, traceable to the "
            "source document, topic-relevant, and directly supported."
        ),
        "event_state": "negative",
        "topics": topics,
    }


# ============================================================
# EVENT-TYPE SPECIFIC VALIDATION
# ============================================================

def event_type_validation(
    excerpt,
    evidence_type
):

    normalized = normalize(
        excerpt
    )

    reasons = []
    score = 0

    # --------------------------------------------------------
    # LAND ACQUISITION
    # --------------------------------------------------------

    if evidence_type == "land_acquisition":

        land_terms = [
            "land",
            "acre",
            "acres",
            "hectare",
            "property",
        ]

        acquisition_terms = [
            "acquired",
            "acquisition",
            "purchased",
            "purchase",
            "bought",
        ]

        if not any(
            term in normalized
            for term in land_terms
        ):
            return (
                -30,
                ["land/real-estate asset not detected"]
            )

        if any(
            term in normalized
            for term in acquisition_terms
        ):

            score += 20

            reasons.append(
                "land acquisition language detected"
            )

        else:

            # Development of already-owned land
            # is not necessarily acquisition.
            score -= 5

            reasons.append(
                "land detected but acquisition action is unclear"
            )

    # --------------------------------------------------------
    # LAND DEVELOPMENT
    # --------------------------------------------------------

    elif evidence_type == "land_development":

        land_terms = [
            "land",
            "acre",
            "acres",
            "hectare",
            "property",
            "site",
        ]

        development_terms = [
            "develop",
            "development",
            "developed",
            "proposed",
            "planned",
            "envisaged",
            "commence development",
        ]

        acquisition_terms = [
            "acquired",
            "acquisition",
            "purchased",
            "purchase",
            "bought",
        ]

        if not any(term in normalized for term in land_terms):
            return (
                -30,
                ["land/property context not detected"]
            )

        if not any(term in normalized for term in development_terms):
            return (
                -25,
                ["land development action is not explicitly supported"]
            )

        # Existing land being developed is NOT land acquisition.
        if any(term in normalized for term in acquisition_terms):
            reasons.append(
                "land acquisition language also present; classification should be reviewed"
            )

        if (
            "awaiting approval" in normalized
            or "awaiting finalization" in normalized
            or "subject to approval" in normalized
            or "government approval" in normalized
            or "regulatory approval" in normalized
        ):
            score += 25
            reasons.append(
                "planned land development is explicitly approval-dependent"
            )
        else:
            score += 20
            reasons.append(
                "planned/proposed land development context detected"
            )

    # --------------------------------------------------------
    # FACILITY CONSTRUCTION
    # --------------------------------------------------------

    elif evidence_type == "facility_construction":

        if has_physical_consequence(
            excerpt
        ):

            score += 20

            reasons.append(
                "physical construction/development context detected"
            )

        else:

            score -= 15

    # --------------------------------------------------------
    # NEW FACILITY
    # --------------------------------------------------------

    elif evidence_type == "new_facility":

        new_facility_terms = [

            "new facility",
            "new plant",
            "new factory",

            "greenfield",

            "new manufacturing",
            "new site",

            "new office",
            "new warehouse",

            "establish",
            "established",

            "construct",
            "construction",
        ]

        if any(
            term in normalized
            for term in new_facility_terms
        ):

            score += 20

            reasons.append(
                "new facility context detected"
            )

        else:

            score -= 10

    # --------------------------------------------------------
    # CAPACITY
    # --------------------------------------------------------

    elif evidence_type == "capacity_expansion":

        capacity_terms = [

            "capacity",
            "production capacity",
            "manufacturing capacity",
            "installed capacity",
            "processing capacity",

            "production blocks",

            "increase capacity",
            "capacity expansion",
        ]

        if any(
            term in normalized
            for term in capacity_terms
        ):

            score += 20

            reasons.append(
                "capacity language detected"
            )

        else:

            score -= 15

    # --------------------------------------------------------
    # OFFICE
    # --------------------------------------------------------

    elif evidence_type == "office_expansion":

        office_terms = [

            "office",
            "headquarters",
            "corporate office",
            "corporate campus",
            "workplace",
        ]

        if any(
            term in normalized
            for term in office_terms
        ):

            score += 20

            reasons.append(
                "office/workplace context detected"
            )

        else:

            score -= 15

    # --------------------------------------------------------
    # WAREHOUSE / DISTRIBUTION
    # --------------------------------------------------------

    elif evidence_type == "warehouse_distribution":

        warehouse_terms = [

            "warehouse",
            "distribution centre",
            "distribution center",
            "logistics facility",
            "logistics centre",
            "logistics center",
        ]

        if any(
            term in normalized
            for term in warehouse_terms
        ):

            score += 20

            reasons.append(
                "warehouse/distribution context detected"
            )

        else:

            score -= 15

    # --------------------------------------------------------
    # TECHNOLOGY
    # --------------------------------------------------------

    elif evidence_type == "technology_transformation":

        technology_terms = [

            "digital transformation",
            "digitalisation",
            "digitization",

            "automation",

            "artificial intelligence",
            "machine learning",

            "technology modernization",
            "technology transformation",

            "erp",
            "cloud migration",
        ]

        if any(
            term in normalized
            for term in technology_terms
        ):

            score += 20

            reasons.append(
                "technology transformation context detected"
            )

        else:

            score -= 15

    # --------------------------------------------------------
    # SUSTAINABILITY
    # --------------------------------------------------------

    elif evidence_type == "sustainability":

        sustainability_terms = [

            "net zero",
            "net-zero",

            "renewable energy",

            "solar",
            "wind energy",

            "decarbonisation",
            "decarbonization",

            "emissions reduction",

            "carbon reduction",

            "clean energy",
        ]

        if any(
            term in normalized
            for term in sustainability_terms
        ):

            score += 20

            reasons.append(
                "sustainability initiative detected"
            )

        else:

            score -= 15

    # --------------------------------------------------------
    # HIRING
    # --------------------------------------------------------

    elif evidence_type == "hiring":

        hiring_terms = [

            "hiring",
            "hired",
            "recruitment",
            "recruiting",
            "recruit",

            "headcount",
            "employees",
            "workforce",

            "new hires",
        ]

        if any(
            term in normalized
            for term in hiring_terms
        ):

            score += 20

            reasons.append(
                "workforce growth context detected"
            )

        else:

            score -= 15

    # --------------------------------------------------------
    # WORKFORCE REDUCTION
    # --------------------------------------------------------

    elif evidence_type == "workforce_reduction":

        reduction_terms = [

            "layoff",
            "layoffs",

            "job cuts",

            "workforce reduction",

            "headcount reduction",

            "downsizing",

            "redundancy",
            "redundancies",

            "employee reduction",
        ]

        if any(
            term in normalized
            for term in reduction_terms
        ):

            score += 20

            reasons.append(
                "workforce reduction context detected"
            )

        else:

            score -= 15

    return (
        score,
        reasons
    )


# ============================================================
# MAIN VALIDATION
# ============================================================

def _has_any(text, terms):
    normalized = normalize(text)
    return any(term in normalized for term in terms)


def _event_support(evidence_type, excerpt, supplied_state=None):
    """Deterministic event-type support. Semantic similarity is advisory only."""

    normalized = normalize(excerpt)
    state = _normalize_event_state(supplied_state)
    reasons = []

    def ok(reason):
        reasons.append(reason)
        return True, reasons

    if evidence_type == "acquisition":
        if _has_any(normalized, [
            "acquired", "acquisition of", "acquisition", "purchased", "purchase of",
            "bought", "remaining stake", "stake of", "equity share capital",
        ]):
            return ok("explicit acquisition/purchase language detected")
        return False, ["no explicit acquisition/purchase action detected"]

    if evidence_type == "merger":
        if _has_any(normalized, [
            "amalgamation", "amalgamated", "merger", "merged", "scheme of amalgamation",
            "scheme of arrangement", "demerger", "corporate combination", "became effective",
        ]):
            return ok("explicit merger/amalgamation/corporate-combination language detected")
        return False, ["no explicit merger/amalgamation action detected"]

    if evidence_type == "leadership_change":
        if validate_leadership_context(excerpt):
            return ok("senior leadership role and concrete leadership action detected")
        return False, ["no concrete senior leadership appointment/resignation/replacement detected"]

    if evidence_type == "land_acquisition":
        has_land = _has_any(normalized, ["land", "acre", "acres", "hectare", "property", "parcel"])
        has_acquisition = _has_any(normalized, ["acquired", "acquisition", "purchased", "purchase", "bought"])
        if has_land and has_acquisition:
            return ok("land/property and explicit acquisition language detected")
        return False, ["land acquisition requires both a land/property asset and an explicit acquisition action"]

    if evidence_type == "land_development":
        has_land = _has_any(normalized, ["land", "acre", "acres", "hectare", "property", "site"])
        has_dev = _has_any(normalized, ["develop", "development", "developed", "proposed", "planned", "commence development"])
        if has_land and has_dev:
            return ok("land and explicit development/planning language detected")
        return False, ["land-development event requires land/property plus development language"]

    if evidence_type == "facility_construction":
        facility = _has_any(normalized, [
            "facility", "plant", "factory", "manufacturing unit", "manufacturing facility",
            "site", "warehouse", "office", "campus", "headquarters",
        ])
        physical_action = _has_any(normalized, [
            "construct", "construction", "constructed", "build", "building",
            "develop", "development", "set up", "setting up", "establish", "established",
            "under construction", "project is progressing", "project progressing",
            "commenced", "groundbreaking",
        ])
        if facility and physical_action:
            return ok("facility and physical development/setup language detected")
        return False, ["facility construction requires a facility/site plus physical development or setup language"]

    if evidence_type == "new_facility":
        new_terms = [
            "new facility", "new plant", "new factory", "new manufacturing", "new site",
            "new office", "new warehouse", "greenfield", "set up", "setting up", "establish",
            "established", "construct", "construction",
        ]
        if _has_any(normalized, new_terms):
            return ok("new-facility creation/setup language detected")
        return False, ["no explicit new-facility creation/setup language detected"]

    if evidence_type == "facility_expansion":
        facility = _has_any(normalized, ["facility", "plant", "factory", "site", "office", "warehouse", "campus"])
        expansion = _has_any(normalized, ["expand", "expanded", "expansion", "augment", "augmentation", "upgrade", "upgraded", "scale-up", "scaled up", "brownfield"])
        if facility and expansion:
            return ok("facility and explicit expansion/upgrade language detected")
        return False, ["facility expansion requires a facility and explicit expansion/upgrade action"]

    if evidence_type == "capacity_expansion":
        capacity = _has_any(normalized, [
            "capacity", "production capacity", "manufacturing capacity", "installed capacity",
            "processing capacity", "throughput", "production blocks", "volume capacity",
        ])
        increase = _has_any(normalized, [
            "increase", "increased", "expansion", "expanded", "expand", "augmentation",
            "augmented", "scaled up", "scale-up", "de-bottleneck", "additional capacity",
            "2.5x", "60%",
        ])
        if capacity and increase:
            return ok("capacity and explicit increase/expansion language detected")
        return False, ["capacity expansion requires capacity plus an explicit increase/expansion signal"]

    if evidence_type == "plant_commissioning":
        if _has_any(normalized, [
            "commissioned", "commissioning", "commercial production", "commercial operations",
            "operations commenced", "operations have commenced", "production commenced", "started operations",
        ]):
            return ok("plant commissioning/startup/operations language detected")
        return False, ["no commissioning/startup/operations language detected"]

    if evidence_type == "warehouse_distribution":
        asset = _has_any(normalized, ["warehouse", "distribution centre", "distribution center", "logistics facility", "logistics centre", "logistics center"])
        action = _has_any(normalized, ["develop", "development", "open", "opened", "establish", "established", "acquire", "acquired", "expand", "expanded", "set up", "setting up"])
        if asset and action:
            return ok("warehouse/distribution asset and action detected")
        return False, ["warehouse/distribution event requires an asset and an operational/physical action"]

    if evidence_type == "office_expansion":
        office = _has_any(normalized, ["office", "headquarters", "corporate office", "corporate campus", "workplace"])
        action = _has_any(normalized, ["expand", "expanded", "expansion", "develop", "development", "open", "opened", "relocat", "relocation", "acquire", "acquired", "construct", "construction", "set up", "setting up"])
        if office and action:
            return ok("office/workplace asset and physical action detected")
        return False, ["office expansion requires an office/workplace asset and a concrete physical action"]

    if evidence_type == "geographic_expansion":
        geographic = _has_any(normalized, ["new market", "new geography", "new region", "new state", "new city", "new country", "presence in", "presence across", "expanded into", "expansion into", "footprint", "network expanded", "stores", "branches", "outlets"])
        if geographic:
            return ok("new geographic presence/market/footprint language detected")
        return False, ["no explicit geographic expansion or new-market presence detected"]

    if evidence_type == "hiring":
        if _has_any(normalized, ["hiring", "hired", "recruitment", "recruiting", "recruit", "headcount", "new hires", "workforce expansion", "increase in employees"]):
            return ok("workforce growth/hiring language detected")
        return False, ["no hiring/workforce-growth language detected"]

    if evidence_type == "workforce_reduction":
        if _has_any(normalized, ["layoff", "layoffs", "job cuts", "workforce reduction", "headcount reduction", "downsizing", "redundancy", "redundancies", "employee reduction"]):
            return ok("workforce reduction language detected")
        return False, ["no workforce-reduction language detected"]

    if evidence_type == "technology_transformation":
        if _has_any(normalized, ["digital transformation", "digitalisation", "digitization", "automation", "artificial intelligence", "machine learning", "technology modernization", "technology transformation", "erp", "cloud migration", "next-generation technology"]):
            return ok("material technology/automation transformation language detected")
        return False, ["no material technology-transformation action detected"]

    if evidence_type == "sustainability":
        if _has_any(normalized, ["net zero", "net-zero", "renewable energy", "solar", "wind energy", "decarbonisation", "decarbonization", "emissions reduction", "carbon reduction", "clean energy"]):
            return ok("material sustainability/clean-energy initiative detected")
        return False, ["no material sustainability initiative detected"]

    if evidence_type == "investment":
        if _has_any(normalized, ["investment", "invested", "investing", "capital expenditure", "capex", "capital allocation", "funding", "financial commitment"]):
            return ok("investment/capital-commitment language detected")
        return False, ["no explicit investment/capital-commitment language detected"]

    return False, ["no deterministic validation rule for evidence type"]


def _infer_state_for_type(evidence_type, excerpt):
    """Fallback state inference used only when Gemini did not provide event_state."""
    inferred = _sentence_state_signals(excerpt)

    if inferred == "context":
        if evidence_type in {"merger", "acquisition", "leadership_change", "plant_commissioning", "capacity_expansion"}:
            if _has_any(excerpt, [
                "acquired", "acquisition", "appointed", "amalgamated", "became effective",
                "commissioned", "completed", "expanded", "increased",
            ]):
                return "actual"

    return inferred


def validate_evidence(evidence, document):

    # ========================================================
    # BASIC SOURCE VALIDATION
    # ========================================================
    if not document:
        return {"status": "rejected", "reason": "Source document does not exist."}

    if not getattr(document, "url", None):
        return {"status": "rejected", "reason": "Source document does not have a URL."}

    if not getattr(document, "raw_text", None):
        return {"status": "rejected", "reason": "Source document does not contain raw text."}

    if not evidence:
        return {"status": "rejected", "reason": "Evidence object does not exist."}

    excerpt = (getattr(evidence, "excerpt", None) or "").strip()

    if not excerpt:
        return {"status": "rejected", "reason": "Evidence excerpt is empty."}

    if len(excerpt) < MIN_EXCERPT_LENGTH:
        return {"status": "rejected", "reason": "Evidence excerpt is too short."}

    if len(excerpt.split()) < MIN_WORD_COUNT:
        return {"status": "rejected", "reason": "Evidence excerpt contains too few words."}

    # ========================================================
    # TRACEABILITY — HARD GATE
    # ========================================================
    if not excerpt_exists_in_document(excerpt, document.raw_text):
        return {
            "status": "rejected",
            "reason": "Evidence excerpt was not found in the source document.",
            "source_traceability": False,
        }

    evidence_type = getattr(evidence, "evidence_type", None)

    if evidence_type not in VALID_EVIDENCE_TYPES:
        return {
            "status": "rejected",
            "reason": "Evidence type is not recognized.",
            "source_traceability": True,
        }

    # ========================================================
    # STATE — USE GEMINI STATE WHEN PROVIDED
    # ========================================================
    supplied_state = getattr(evidence, "event_state", None)
    state = _normalize_event_state(supplied_state)

    # Preserve Gemini's explicit state for the final validation result.
    # Only infer a state when Gemini omitted event_state entirely.
    if not state:
        state = _infer_state_for_type(evidence_type, excerpt)

    if state == "negative":
        return {
            "status": "rejected",
            "reason": "Passage describes a negative/no-change condition rather than a positive business event.",
            "event_state": state,
            "source_traceability": True,
        }

    # Do NOT re-infer or overwrite an explicit Gemini state.
    # "context" is a legitimate model state and must remain "context".
    # Event-type validation below determines whether the evidence is valid;
    # it does not rewrite the event's reported state.

    # ========================================================
    # DETERMINISTIC EVENT-TYPE VALIDATION
    # ========================================================
    supported, support_reasons = _event_support(
        evidence_type,
        excerpt,
        state,
    )

    if not supported:
        return {
            "status": "rejected",
            "reason": support_reasons[0],
            "event_state": state,
            "source_traceability": True,
            "validation_basis": "deterministic_event_type_rule",
        }

    # ========================================================
    # OPTIONAL SEMANTIC / LINGUISTIC DIAGNOSTICS
    # ========================================================
    semantic_score, semantic_similarity, semantic_reasons = semantic_validation(
        excerpt,
        evidence_type,
    )

    linguistic_score, linguistic_reasons = linguistic_validation(
        excerpt,
        evidence_type,
    )

    event_score = 25
    validation_score = max(
        0,
        min(
            MAX_VALIDATION_SCORE,
            50 + semantic_score + linguistic_score + event_score,
        ),
    )

    # Semantic similarity is deliberately NOT a hard rejection once the
    # source is traceable and the event-specific deterministic rule passes.
    reasons = (
        support_reasons
        + semantic_reasons
        + linguistic_reasons
    )

    return {
        "status": "validated",
        "reason": "Evidence is traceable and satisfies the deterministic event-type validation rule.",
        "validation_score": validation_score,
        "semantic_similarity": round(semantic_similarity, 4),
        "event_state": state,
        "source_traceability": True,
        "validation_basis": "deterministic_event_type_rule",
        "analysis": reasons,
    }

