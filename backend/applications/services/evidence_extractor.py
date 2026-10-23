import re
from functools import lru_cache


from applications.models.evidence import Evidence


# ============================================================
# CONFIGURATION
# ============================================================

MAX_EXCERPT_LENGTH = 1000
MIN_EXCERPT_LENGTH = 60
MIN_WORD_COUNT = 8

SEMANTIC_THRESHOLD = 0.34
STRONG_SEMANTIC_THRESHOLD = 0.48

MAX_CANDIDATES_PER_TYPE = 8
MAX_SIGNALS = 40

# Broader event-discovery vocabulary used ONLY by the expanded LLM retrieval path.
# This deliberately catches secondary operational/geographic events that may not
# rank highly enough under the original semantic signal definitions.
LLM_EVENT_DISCOVERY_PATTERNS = {
    "capacity_expansion": [
        r"\bcapacity\b", r"\bcapacities\b", r"\bproduction\b",
        r"\boutput\b", r"\bthroughput\b", r"\btonnes?\b", r"\bmtpa\b",
        r"\bklpa\b", r"\bexpanded?\b", r"\bexpansion\b",
        r"\baugmented?\b", r"\baugmentation\b", r"\bscaled?\b",
        r"\bincreased?\b", r"\bde[- ]?bottleneck", r"\badditional capacity\b",
    ],
    "geographic_expansion": [
        r"\bexpanded?\b.*\b(store|stores|branch|branches|outlet|outlets|network|presence|footprint|state|states|city|cities|country|countries|market|markets)\b",
        r"\b(store|stores|branch|branches|outlet|outlets)\b.*\b(expand|expanded|expansion|opened|openings|network)\b",
        r"\b\d+[,.]?\d*\s+(?:stores?|branches|outlets)\b",
        r"\bnew (market|markets|geograph|region|regions|state|states|city|cities|country|countries)\b",
        r"\bpresence\b.*\b(across|in|throughout)\b",
        r"\bfootprint\b.*\b(expand|expanded|expansion|increase|increased)\b",
    ],
    "facility_expansion": [
        r"\bfacility\b.*\b(expand|expanded|expansion|scale|scaled|augment|augmented|upgrade|upgraded)\b",
        r"\bplant\b.*\b(expand|expanded|expansion|scale|scaled|augment|augmented|upgrade|upgraded)\b",
        r"\bsite\b.*\b(expand|expanded|expansion|augment|augmented)\b",
        r"\badditional (line|lines|block|blocks|unit|units|fume hoods?|labs?|laboratories)\b",
    ],
    "office_expansion": [
        r"\bheadquarters?\b.*\b(construct|construction|build|building|expand|expansion|develop)\b",
        r"\boffice\b.*\b(expand|expanded|expansion|open|opened|relocat|develop|construct)\b",
        r"\bcorporate office\b",
    ],
    "new_facility": [
        r"\bnew (plant|facility|factory|site|office|warehouse|store|stores|centre|center|campus|headquarters?)\b",
        r"\b(establish|established|set up|setup|open|opened|commissioned)\b.*\b(plant|facility|factory|site|office|warehouse|store|stores|centre|center)\b",
    ],
    "plant_commissioning": [
        r"\b(commissioned|commissioning|commercial production|commenced operations|started production|production commenced)\b",
    ],
    "acquisition": [r"\b(acquire|acquired|acquisition|stake|shares?)\b"],
    "merger": [r"\b(merger|amalgamation|scheme of arrangement|demerger)\b"],
    "leadership_change": [
        r"\b(appointed|appointment|reappointed|resigned|retired|retirement)\b.*\b(director|chief|ceo|cfo|management|leadership|president)\b",
        r"\b(director|ceo|cfo|management|leadership)\b.*\b(appointed|appointment|resigned|retired)\b",
    ],
    "technology_transformation": [
        r"\b(new technology|technology platform|digital transformation|automation|moderni[sz]ation|ai|artificial intelligence|machine learning)\b",
    ],
    "sustainability": [
        r"\b(solar|renewable|decarbon|net[- ]zero|emissions reduction|green energy)\b",
    ],
}

LLM_EVENT_MIN_LEXICAL_SCORE = 1
LLM_EVENT_MAX_LEXICAL_CANDIDATES = 350



# ============================================================
# EVIDENCE TYPES
# ============================================================

EVIDENCE_TYPES = {
    "investment",
    "capacity_expansion",
    "facility_expansion",
    "new_facility",
    "facility_construction",
    "plant_commissioning",
    "land_acquisition",
    "warehouse_distribution",
    "office_expansion",
    "geographic_expansion",
    "hiring",
    "leadership_change",
    "acquisition",
    "merger",
    "technology_transformation",
    "sustainability",
}


# ============================================================
# SEMANTIC DEFINITIONS
# ============================================================

SIGNAL_DEFINITIONS = {

    "investment":
        "The company is actually investing, committing capital, "
        "funding a project, spending capital, or planning a material "
        "business investment.",

    "capacity_expansion":
        "The company is increasing production capacity, manufacturing "
        "capacity, operational capacity, or adding capacity.",

    "facility_expansion":
        "The company is expanding or upgrading an existing physical facility, plant, site, office, property, campus, warehouse, or other physical location.",

    "new_facility":
        "The company is establishing, constructing, opening, acquiring, or planning a new plant, factory, office, warehouse, campus, headquarters, or physical site.",

    "facility_construction":
        "The company is constructing or developing a physical facility, plant, factory, building, site, or other built environment.",

    "plant_commissioning":
        "A new or expanded plant, production block, manufacturing unit, or facility has started or is scheduled to start operations or commercial production.",

    "land_acquisition":
        "The company has acquired or purchased land or a physical parcel for a current or future business development.",

    "warehouse_distribution":
        "The company is developing, expanding, opening, or planning warehouses, distribution centres, logistics facilities, or supply-chain infrastructure.",

    "office_expansion":
        "The company is expanding, opening, relocating, or developing offices, campuses, headquarters, or corporate workplaces.",

    "geographic_expansion":
        "The company is entering or materially expanding operations into a new city, region, state, country, or geographic market.",

    "new_facility":
        "The company is establishing, constructing, opening, acquiring, "
        "or planning a new plant, factory, office, warehouse, campus, "
        "headquarters, or physical site.",

    "hiring":
        "The company is materially increasing its workforce, hiring "
        "employees, recruiting for expansion, or planning workforce growth.",

    "leadership_change":
        "An actual senior executive or board leadership appointment, "
        "resignation, retirement, replacement, reappointment, or other "
        "leadership change has occurred.",

    "acquisition":
        "The company has acquired, agreed to acquire, purchased, or "
        "announced a business acquisition.",

    "merger":
        "The company has entered into, completed, or announced a merger, "
        "amalgamation, demerger, or scheme of arrangement.",

    "technology_transformation":
        "The company is implementing a material technology transformation, "
        "digital transformation, automation, artificial intelligence, "
        "machine learning, or major technology modernization.",

    "sustainability":
        "The company is implementing a material sustainability, renewable "
        "energy, decarbonization, emissions reduction, or net-zero initiative.",
}


# ============================================================
# EVENT / STATE WORDS
# ============================================================

ACTUAL_WORDS = {
    "completed",
    "commissioned",
    "opened",
    "launched",
    "acquired",
    "appointed",
    "reappointed",
    "resigned",
    "retired",
    "renewed",
    "constructed",
    "installed",
    "started",
    "commenced",
    "implemented",
    "established",
}

PLANNING_WORDS = {
    "planned",
    "plan",
    "plans",
    "planning",
    "proposed",
    "proposal",
    "intends",
    "intended",
    "will",
    "expected",
    "expects",
    "proposes",
    "envisaged",
    "target",
    "targeted",
    "to be developed",
    "to be constructed",
    "to be established",
}

PENDING_WORDS = {
    "awaiting",
    "pending",
    "subject to approval",
    "subject to approvals",
    "awaiting approval",
    "awaiting finalization",
    "approval awaited",
    "under approval",
    "regulatory approval",
    "government approval",
}

HISTORICAL_WORDS = {
    "previous year",
    "earlier year",
    "historically",
    "in the past",
    "prior year",
    "during the year",
    "last year",
}

NEGATIVE_STATE_WORDS = {
    "no change",
    "no changes",
    "there is no change",
    "there are no changes",
    "did not",
    "does not",
    "no new",
    "not commenced",
    "not started",
    "none",
    "nil",
    "not applicable",
}


# ============================================================
# ACTION WORDS
# ============================================================

ACTION_WORDS = {
    "acquire",
    "acquired",
    "acquisition",
    "appoint",
    "appointed",
    "reappointed",
    "construct",
    "constructed",
    "build",
    "built",
    "develop",
    "developed",
    "development",
    "expand",
    "expanded",
    "expansion",
    "establish",
    "established",
    "invest",
    "invested",
    "investment",
    "launch",
    "launched",
    "open",
    "opened",
    "increase",
    "increased",
    "commission",
    "commissioned",
    "implement",
    "implemented",
    "install",
    "installed",
    "renew",
    "renewed",
    "upgrade",
    "upgraded",
    "hire",
    "hiring",
    "recruit",
    "recruitment",
}


# ============================================================
# BOILERPLATE / NON-EVENT CONTEXT
# ============================================================

BOILERPLATE_PATTERNS = [

    # Governance
    r"\bcorporate governance\b",
    r"\bterms of reference\b",
    r"\bcommittee\b",
    r"\bcommittee composition\b",
    r"\bcommittee shall\b",
    r"\bcommittee is responsible\b",
    r"\bboard committee\b",

    # Policies / definitions
    r"\bpolicy\b",
    r"\bpolicies\b",
    r"\bdefinition\b",
    r"\bdefinitions\b",
    r"\bcriteria for selection\b",
    r"\bcriteria for appointment\b",
    r"\bcriteria for selecting\b",
    r"\bprocess for appointment\b",
    r"\bprocess of appointment\b",

    # Accounting
    r"\baccounting policy\b",
    r"\baccounting policies\b",
    r"\baccounting standard\b",
    r"\bmeasured initially at cost\b",
    r"\bsubsequent to initial recognition\b",
    r"\bcarrying amount\b",
    r"\bfair value\b",
    r"\bdepreciation policy\b",

    # Auditing
    r"\bauditor\b",
    r"\bauditors\b",
    r"\bauditing\b",
    r"\baudit committee\b",
    r"\bstatutory audit\b",
    r"\binternal audit\b",

    # Generic governance / compliance
    r"\bcompliance\b",
    r"\bremuneration\b",
    r"\brisk management\b",
    r"\bshareholder\b",
    r"\bshareholders\b",
    r"\bdividend\b",
    r"\bfinancial statements\b",
    r"\bsecretarial standards\b",

    # Generic definitions
    r"\bfor the purpose of\b",
    r"\bunder the act\b",
    r"\bshall mean\b",
    r"\bis defined as\b",
]


# ============================================================
# SIGNAL-SPECIFIC RULES
# ============================================================

LEADERSHIP_ROLES = [
    r"\bchief executive officer\b",
    r"\bchief financial officer\b",
    r"\bchief operating officer\b",
    r"\bchief technology officer\b",
    r"\bchief human resources officer\b",
    r"\bceo\b",
    r"\bcfo\b",
    r"\bcoo\b",
    r"\bcto\b",
    r"\bchro\b",
    r"\bmanaging director\b",
    r"\bexecutive director\b",
    r"\bindependent director\b",
    r"\bwhole[- ]time director\b",
    r"\bnon[- ]executive director\b",
    r"\bchairman\b",
    r"\bchairperson\b",
    r"\bpresident\b",
]

LEADERSHIP_ACTIONS = [
    r"\bappointed\b",
    r"\bappointment\b",
    r"\breappointed\b",
    r"\breappointment\b",
    r"\bresigned\b",
    r"\bresignation\b",
    r"\bretired\b",
    r"\bretirement\b",
    r"\bceased\b",
    r"\breplaced\b",
    r"\breplacement\b",
    r"\bjoined\b",
]

INVESTMENT_ACTIONS = [
    r"\binvested\b",
    r"\binvestment\b",
    r"\binvesting\b",
    r"\bcapital expenditure\b",
    r"\bcapex\b",
    r"\bcapital investment\b",
    r"\bcapital commitment\b",
    r"\bcommitted .* capital\b",
    r"\bwill invest\b",
    r"\bplans to invest\b",
    r"\bproposes to invest\b",
]

PHYSICAL_TERMS = [
    r"\bland\b",
    r"\bproperty\b",
    r"\bsite\b",
    r"\bfacility\b",
    r"\bplant\b",
    r"\bfactory\b",
    r"\bwarehouse\b",
    r"\boffice\b",
    r"\bcampus\b",
    r"\bheadquarters\b",
    r"\bbuilding\b",
    r"\bmanufacturing unit\b",
    r"\bdistribution centre\b",
    r"\bdistribution center\b",
]


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
def get_sentence_model():
    # Import lazily so a blocked/broken SciPy native DLL does not prevent
    # Flask and unrelated API routes from starting.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        "all-MiniLM-L6-v2"
    )


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_whitespace(text):
    if not text:
        return ""

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


# spaCy refuses texts longer than nlp.max_length. Annual reports can
# easily exceed that limit, so large documents are sentence-segmented in
# overlapping-safe chunks. Chunk boundaries are chosen at whitespace so
# words are never split in the middle.
SPACY_CHUNK_SIZE = 500_000


def _split_text_for_spacy(text, chunk_size=SPACY_CHUNK_SIZE):
    """
    Split very large text into whitespace-safe chunks for spaCy.

    The chunks intentionally overlap by no characters: sentence boundaries
    are reconstructed by treating each chunk independently, while the
    original text remains unchanged for all downstream traceability checks.
    """

    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = min(start + chunk_size, text_length)

        if end < text_length:
            # Prefer a whitespace boundary so we do not cut a word in half.
            boundary = text.rfind(" ", start, end)
            if boundary > start:
                end = boundary

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        # Move past the whitespace boundary.
        start = end
        while start < text_length and text[start].isspace():
            start += 1

    return chunks


def split_into_sentences(text):
    """
    Use spaCy sentence segmentation rather than regex-only splitting.

    Large annual reports are processed in safe chunks because spaCy has a
    default maximum input length of 1,000,000 characters. This keeps the
    existing sentence segmentation and retrieval logic unchanged while
    allowing reports larger than that limit to be processed.
    """

    if not text:
        return []

    nlp = get_spacy_model()
    chunks = _split_text_for_spacy(text)

    if len(chunks) > 1:
        print(
            f"spaCy large-document mode: {len(text):,} characters "
            f"split into {len(chunks)} chunks"
        )

    sentences = []

    for chunk in chunks:
        doc = nlp(chunk)

        for sentence in doc.sents:
            value = normalize_whitespace(sentence.text)

            if value:
                sentences.append(value)

    return sentences


# ============================================================
# CHUNK CREATION
# ============================================================

def build_chunks(sentences):
    """
    Create small context windows.

    Each chunk contains:
        previous sentence
        current sentence
        next sentence
    """

    chunks = []

    for index, sentence in enumerate(sentences):

        start = max(
            0,
            index - 1
        )

        end = min(
            len(sentences),
            index + 2
        )

        chunk = " ".join(
            sentences[start:end]
        )

        chunks.append({
            "text": chunk,
            "sentence_index": index,
        })

    return chunks


# ============================================================
# BOILERPLATE DETECTION
# ============================================================

def is_boilerplate(text):

    lower = text.lower()

    matched = 0

    for pattern in BOILERPLATE_PATTERNS:

        if re.search(
            pattern,
            lower,
            re.IGNORECASE
        ):
            matched += 1

    strong_patterns = [
        r"\baccounting policy\b",
        r"\bterms of reference\b",
        r"\bcriteria for selection\b",
        r"\bcriteria for appointment\b",
        r"\bstatutory auditor\b",
        r"\bauditor\b",
        r"\bfinancial statements\b",
    ]

    for pattern in strong_patterns:

        if re.search(
            pattern,
            lower,
            re.IGNORECASE
        ):
            return True

    return matched >= 2


# ============================================================
# STATE CLASSIFICATION
# ============================================================

def classify_state(text):

    lower = text.lower()

    # Negative state has priority.
    for phrase in NEGATIVE_STATE_WORDS:

        if phrase in lower:
            return "negative"

    for phrase in PENDING_WORDS:

        if phrase in lower:
            return "pending"

    for phrase in PLANNING_WORDS:

        if phrase in lower:
            return "planned"

    for phrase in ACTUAL_WORDS:

        if phrase in lower:
            return "actual"

    for phrase in HISTORICAL_WORDS:

        if phrase in lower:
            return "historical"

    return "context"


# ============================================================
# EVENT-SPECIFIC VALIDATION
# ============================================================

def validate_signal_type(signal_type, text):

    lower = text.lower()

    # --------------------------------------------------------
    # LEADERSHIP
    # --------------------------------------------------------

    if signal_type == "leadership_change":

        has_role = any(
            re.search(
                pattern,
                lower,
                re.IGNORECASE
            )
            for pattern in LEADERSHIP_ROLES
        )

        has_action = any(
            re.search(
                pattern,
                lower,
                re.IGNORECASE
            )
            for pattern in LEADERSHIP_ACTIONS
        )

        if not has_role or not has_action:
            return False

        # Reject generic selection/appointment policies.
        if re.search(
            r"criteria for|selection of|process for|"
            r"terms of reference|appointment of directors.*criteria",
            lower,
            re.IGNORECASE
        ):
            return False

        return True

    # --------------------------------------------------------
    # INVESTMENT
    # --------------------------------------------------------

    if signal_type == "investment":

        has_action = any(
            re.search(
                pattern,
                lower,
                re.IGNORECASE
            )
            for pattern in INVESTMENT_ACTIONS
        )

        if not has_action:
            return False

        # Accounting policy is not an investment event.
        if re.search(
            r"accounting policy|investment properties are measured|"
            r"subsequent to initial recognition|fair value",
            lower,
            re.IGNORECASE
        ):
            return False

        return True

    # --------------------------------------------------------
    # PHYSICAL / FACILITY SIGNALS
    # --------------------------------------------------------

    if signal_type in {
        "facility_expansion",
        "new_facility",
        "capacity_expansion",
    }:

        has_physical_term = any(
            re.search(
                pattern,
                lower,
                re.IGNORECASE
            )
            for pattern in PHYSICAL_TERMS
        )

        has_action = any(
            word in lower
            for word in [
                "develop",
                "development",
                "construct",
                "construction",
                "expand",
                "expansion",
                "build",
                "building",
                "establish",
                "established",
                "commission",
                "commissioned",
                "capacity",
                "plant",
                "facility",
                "site",
                "land",
            ]
        )

        return (
            has_physical_term
            and has_action
        )

    # --------------------------------------------------------
    # HIRING
    # --------------------------------------------------------

    if signal_type == "hiring":

        hiring_terms = [
            "hiring",
            "recruiting",
            "recruitment",
            "employees",
            "workforce",
            "new hires",
            "job openings",
        ]

        return any(
            term in lower
            for term in hiring_terms
        )

    # --------------------------------------------------------
    # ACQUISITION
    # --------------------------------------------------------

    if signal_type == "acquisition":

        return bool(
            re.search(
                r"\bacquir(?:e|ed|ing|ition)\b|"
                r"\btakeover\b|"
                r"\bbuyout\b",
                lower,
                re.IGNORECASE
            )
        )

    # --------------------------------------------------------
    # MERGER
    # --------------------------------------------------------

    if signal_type == "merger":

        return bool(
            re.search(
                r"\bmerger\b|"
                r"\bmerged\b|"
                r"\bamalgamation\b|"
                r"\bdemerger\b|"
                r"\bscheme of arrangement\b",
                lower,
                re.IGNORECASE
            )
        )

    # --------------------------------------------------------
    # TECHNOLOGY
    # --------------------------------------------------------

    if signal_type == "technology_transformation":

        technology_terms = [
            "digital transformation",
            "digitalisation",
            "digitization",
            "automation",
            "artificial intelligence",
            "machine learning",
            "technology transformation",
            "technology modernization",
        ]

        return any(
            term in lower
            for term in technology_terms
        )

    # --------------------------------------------------------
    # SUSTAINABILITY
    # --------------------------------------------------------

    if signal_type == "sustainability":

        sustainability_terms = [
            "net zero",
            "net-zero",
            "decarbonisation",
            "decarbonization",
            "renewable energy",
            "zero emission",
            "zero emissions",
            "clean energy",
        ]

        return any(
            term in lower
            for term in sustainability_terms
        )

    return True


# ============================================================
# SEMANTIC SIGNAL MATCHING
# ============================================================

def semantic_candidates(chunks):

    if not chunks:
        return []

    model = get_sentence_model()

    chunk_texts = [
        chunk["text"]
        for chunk in chunks
    ]

    chunk_embeddings = model.encode(
        chunk_texts,
        convert_to_tensor=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    signal_types = list(
        SIGNAL_DEFINITIONS.keys()
    )

    definitions = [
        SIGNAL_DEFINITIONS[
            signal_type
        ]
        for signal_type in signal_types
    ]

    definition_embeddings = model.encode(
        definitions,
        convert_to_tensor=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    from sentence_transformers import util

    similarity_matrix = util.cos_sim(
        chunk_embeddings,
        definition_embeddings
    )

    candidates = []

    for chunk_index, chunk in enumerate(chunks):

        scores = similarity_matrix[
            chunk_index
        ]

        for signal_index, score in enumerate(scores):

            similarity = float(
                score.item()
            )

            if similarity < SEMANTIC_THRESHOLD:
                continue

            signal_type = signal_types[
                signal_index
            ]

            candidates.append({
                "signal_type": signal_type,
                "text": chunk["text"],
                "sentence_index": chunk["sentence_index"],
                "semantic_similarity": similarity,
            })

    return candidates


# ============================================================
# LINGUISTIC SCORING
# ============================================================

def linguistic_score(signal_type, text):

    lower = text.lower()

    score = 0

    # Action words
    for word in ACTION_WORDS:

        if re.search(
            rf"\b{re.escape(word)}\b",
            lower,
            re.IGNORECASE
        ):
            score += 2

    # Planning language
    for phrase in PLANNING_WORDS:

        if phrase in lower:
            score += 3

    # Pending approvals
    for phrase in PENDING_WORDS:

        if phrase in lower:
            score += 3

    # Physical terms
    for pattern in PHYSICAL_TERMS:

        if re.search(
            pattern,
            lower,
            re.IGNORECASE
        ):
            score += 2

    # Monetary language
    if re.search(
        r"(₹|rs\.?|inr|\$|€|£)\s?[\d,.]+",
        lower,
        re.IGNORECASE
    ):
        score += 4

    # Area / land / capacity measurements
    if re.search(
        r"\b\d+(?:\.\d+)?\s*"
        r"(?:acre|acres|sq\.?\s*ft|sqft|"
        r"square feet|hectare|hectares|mw|gw|"
        r"mt|tonnes?)\b",
        lower,
        re.IGNORECASE
    ):
        score += 4

    # Signal-specific reinforcement
    if signal_type == "leadership_change":

        if any(
            re.search(
                pattern,
                lower,
                re.IGNORECASE
            )
            for pattern in LEADERSHIP_ROLES
        ):
            score += 8

        if any(
            re.search(
                pattern,
                lower,
                re.IGNORECASE
            )
            for pattern in LEADERSHIP_ACTIONS
        ):
            score += 8

    return score


# ============================================================
# FINAL CANDIDATE SCORING
# ============================================================

def score_candidate(candidate):

    signal_type = candidate[
        "signal_type"
    ]

    text = candidate[
        "text"
    ]

    semantic_score = candidate[
        "semantic_similarity"
    ]

    linguistic = linguistic_score(
        signal_type,
        text
    )

    score = (
        semantic_score * 100
        + linguistic
    )

    return score


# ============================================================
# EXCERPT CREATION
# ============================================================

def build_excerpt(text):

    text = normalize_whitespace(
        text
    )

    if len(text) <= MAX_EXCERPT_LENGTH:
        return text

    excerpt = text[
        :MAX_EXCERPT_LENGTH
    ]

    # Prefer ending at a sentence boundary.
    last_period = excerpt.rfind(".")

    if last_period >= MIN_EXCERPT_LENGTH:
        excerpt = excerpt[
            :last_period + 1
        ]

    return excerpt.strip()


# ============================================================
# DEDUPLICATION
# ============================================================

def deduplicate_candidates(candidates):

    seen = set()

    result = []

    for candidate in candidates:

        key = (
            candidate["signal_type"],
            normalize_whitespace(
                candidate["text"]
            ).lower()
        )

        if key in seen:
            continue

        seen.add(key)

        result.append(
            candidate
        )

    return result


# ============================================================
# RICH SIGNAL EXTRACTION HELPERS
# ============================================================

MONEY_PATTERN = re.compile(
    r"(?P<currency>₹|rs\.?|inr|usd|\$|eur|€|gbp|£)\s*"
    r"(?P<amount>[\d,]+(?:\.\d+)?)"
    r"(?:\s*(?P<scale>crore|crores|lakh|lakhs|million|billion|mn|bn|m|k))?",
    re.IGNORECASE,
)

MEASUREMENT_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:acres?|hectares?|ha|sq\.?\s*(?:ft|m|mts?)|sqft|"
    r"square\s+(?:feet|metres?|meters?)|production\s+blocks?|blocks?|"
    r"plants?|units?|labs?|fume\s+hoods?|mw|gw|mt|tonnes?|tons?|employees?)\b",
    re.IGNORECASE,
)

YEAR_PATTERN = re.compile(
    r"\b(?:FY\s*)?20\d{2}(?:[-/]20?\d{2})?\b|\bQ[1-4]\s+FY\s*20\d{2}(?:[-/]20?\d{2})?\b",
    re.IGNORECASE,
)

LOCATION_PATTERNS = [
    re.compile(r"\bat\s+([A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,4})", re.IGNORECASE),
    re.compile(r"\bin\s+([A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,4})", re.IGNORECASE),
    re.compile(r"\b(?:located|situated)\s+(?:at|in)\s+([A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,4})", re.IGNORECASE),
]

PHYSICAL_CONSEQUENCE_MAP = {
    "new_facility": ["new facility", "new physical site", "new workplace / operational site"],
    "facility_construction": ["new or expanded built infrastructure", "facility construction"],
    "facility_expansion": ["expanded physical footprint", "facility upgrade / expansion"],
    "plant_commissioning": ["new production capacity", "operational manufacturing infrastructure"],
    "capacity_expansion": ["increased production capacity", "additional operational capacity"],
    "land_acquisition": ["land available for future development", "potential future physical development"],
    "warehouse_distribution": ["warehouse / distribution infrastructure", "expanded logistics footprint"],
    "office_expansion": ["expanded office / workplace footprint", "new corporate workspace"],
    "geographic_expansion": ["new geographic operating footprint", "potential new facilities or workplaces"],
    "investment": ["capital deployment", "potential physical or operational investment"],
    "hiring": ["workforce growth", "potential workplace / operational requirements"],
    "technology_transformation": ["technology-enabled workplace / operational change"],
    "sustainability": ["sustainability-related infrastructure or facility changes"],
    "leadership_change": [],
    "acquisition": ["potential integration / consolidation requirements"],
    "merger": ["potential integration / consolidation requirements"],
}


def extract_money(text):
    values = []
    for match in MONEY_PATTERN.finditer(text):
        raw = normalize_whitespace(match.group(0))
        values.append({
            "raw": raw,
            "currency": match.group("currency"),
            "amount": match.group("amount"),
            "scale": match.group("scale"),
        })
    return values


def extract_measurements(text):
    return list(dict.fromkeys(
        normalize_whitespace(m.group(0))
        for m in MEASUREMENT_PATTERN.finditer(text)
    ))


def extract_timeline(text):
    values = list(dict.fromkeys(
        normalize_whitespace(m.group(0))
        for m in YEAR_PATTERN.finditer(text)
    ))
    # Include common relative timing phrases when present.
    for phrase in [
        "within the year", "during the year", "next year", "in the coming year",
        "q1", "q2", "q3", "q4", "first quarter", "second quarter",
        "third quarter", "fourth quarter", "by fy", "by year end",
    ]:
        if phrase in text.lower() and phrase not in [v.lower() for v in values]:
            values.append(phrase)
    return values


def extract_locations(text):
    results = []
    for pattern in LOCATION_PATTERNS:
        for match in pattern.finditer(text):
            value = normalize_whitespace(match.group(1)).strip(" ,.;:")
            if not value:
                continue
            # Avoid capturing generic continuation words.
            value = re.split(r"\s+(?:and|with|for|where|which|that)\s+", value, maxsplit=1, flags=re.I)[0]
            if len(value) >= 2 and value.lower() not in {x.lower() for x in results}:
                results.append(value)
    return results[:5]


def infer_physical_consequence(signal_type, text):
    consequences = list(PHYSICAL_CONSEQUENCE_MAP.get(signal_type, []))
    lower = text.lower()
    if any(x in lower for x in ["greenfield", "new plant", "new factory", "new manufacturing"]):
        if "new facility" not in consequences:
            consequences.insert(0, "greenfield / new manufacturing infrastructure")
    if any(x in lower for x in ["office", "headquarters", "campus"]):
        consequences.append("office / workplace footprint")
    if any(x in lower for x in ["land", "parcel", "acre"]):
        consequences.append("land / site development opportunity")
    return list(dict.fromkeys(consequences))


def infer_materiality(candidate):
    score = candidate.get("score", 0)
    text = candidate.get("text", "").lower()
    money = extract_money(text)
    measurements = extract_measurements(text)
    physical = infer_physical_consequence(candidate["signal_type"], text)

    if score >= 75 or money or len(measurements) >= 2 or len(physical) >= 2:
        return "high"
    if score >= 58 or measurements or physical:
        return "medium"
    return "low"


def build_headline(signal_type, state, text, company_name=""):
    subject = company_name.strip() if company_name else "The company"
    lower = text.lower()

    if signal_type in {"new_facility", "facility_construction", "facility_expansion"}:
        action = "is planning a new facility" if state == "planned" else "is developing a physical facility"
    elif signal_type == "plant_commissioning":
        action = "has commissioned or is commissioning a plant"
    elif signal_type == "land_acquisition":
        action = "has acquired land for potential development"
    elif signal_type == "capacity_expansion":
        action = "is expanding capacity"
    elif signal_type == "warehouse_distribution":
        action = "is expanding logistics infrastructure"
    elif signal_type == "office_expansion":
        action = "is expanding its workplace footprint"
    elif signal_type == "geographic_expansion":
        action = "is expanding geographically"
    elif signal_type == "investment":
        action = "is making or planning a material investment"
    elif signal_type == "hiring":
        action = "is expanding its workforce"
    elif signal_type == "leadership_change":
        action = "has a leadership change"
    elif signal_type == "acquisition":
        action = "has an acquisition-related event"
    elif signal_type == "merger":
        action = "has a merger-related event"
    elif signal_type == "technology_transformation":
        action = "is undertaking a technology transformation"
    elif signal_type == "sustainability":
        action = "is undertaking a sustainability initiative"
    else:
        action = "has a material business event"

    location = extract_locations(text)
    if location and signal_type in {"new_facility", "facility_construction", "facility_expansion", "land_acquisition", "warehouse_distribution", "office_expansion", "geographic_expansion"}:
        return f"{subject} {action} at {location[0]}"
    return f"{subject} {action}"


def build_summary(candidate, company_name=""):
    text = build_excerpt(candidate["text"])
    return text


def build_why_it_matters(candidate):
    signal_type = candidate["signal_type"]
    physical = infer_physical_consequence(signal_type, candidate["text"])
    if physical:
        return (
            "This is relevant because it indicates "
            + ", ".join(physical[:2])
            + "."
        )
    return "This is a potentially material business change that may indicate a future opportunity."


def build_rich_signal(candidate, company_name=""):
    text = candidate["text"]
    signal_type = candidate["signal_type"]
    state = candidate["state"]
    excerpt = build_excerpt(text)
    money = extract_money(text)
    measurements = extract_measurements(text)
    timeline = extract_timeline(text)
    locations = extract_locations(text)

    return {
        "signal_type": signal_type,
        "event_state": state,
        "headline": build_headline(signal_type, state, text, company_name),
        "summary": build_summary(candidate, company_name),
        "why_it_matters": build_why_it_matters(candidate),
        "company": company_name or None,
        "location": {
            "mentions": locations,
        },
        "investment": {
            "values": money,
        },
        "physical_scale": measurements,
        "timeline": timeline,
        "physical_consequence": infer_physical_consequence(signal_type, text),
        "supporting_facts": [],
        "evidence": {
            "excerpt": excerpt,
            "sentence_index": candidate["sentence_index"] + 1,
        },
        "confidence": round(min(0.99, max(0.0, candidate["score"] / 100)), 3),
        "semantic_similarity": round(candidate["semantic_similarity"], 3),
        "score": round(candidate["score"], 2),
        "materiality": infer_materiality(candidate),
        "source_quality": "annual_report",
    }


# ============================================================
# DEDUPLICATION OF RICH SIGNALS
# ============================================================

def deduplicate_rich_signals(signals):
    """Keep the strongest signal when the same event appears repeatedly."""
    result = []
    seen = {}

    for signal in signals:
        key = (
            signal["signal_type"],
            signal["event_state"],
            signal["headline"].lower(),
        )
        existing = seen.get(key)
        if existing is None:
            seen[key] = signal
            result.append(signal)
        elif signal["score"] > existing["score"]:
            index = result.index(existing)
            result[index] = signal
            seen[key] = signal

    return result


# ============================================================
# MAIN EXTRACTION
# ============================================================

def extract_evidence(text, company_name=""):
    """Extract rich, standalone business signals from annual-report text.

    This function intentionally has NO database dependency. It returns a list
    of dictionaries containing the business signal, context, extracted facts,
    evidence traceability and scoring information.
    """

    if not text:
        return []

    print("\n[Rich Evidence Extraction]")

    # 1. spaCy document understanding
    sentences = split_into_sentences(text)
    print(f"spaCy sentences: {len(sentences)}")

    if not sentences:
        return []

    # 2. Context windows
    chunks = build_chunks(sentences)
    print(f"Semantic chunks: {len(chunks)}")

    # 3. Semantic retrieval
    candidates = semantic_candidates(chunks)
    print(f"Semantic candidates: {len(candidates)}")

    # 4. Candidate filtering
    qualified = []

    for candidate in candidates:
        candidate_text = candidate["text"]
        signal_type = candidate["signal_type"]
        semantic_similarity = candidate["semantic_similarity"]

        if is_boilerplate(candidate_text):
            continue

        if candidate.get("discovery_source") == "event_lexical":
            if candidate.get("lexical_hits", 0) < LLM_EVENT_MIN_LEXICAL_SCORE:
                continue
        elif (
            semantic_similarity < STRONG_SEMANTIC_THRESHOLD
            and linguistic_score(signal_type, candidate_text) < 5
        ):
            continue

        if not validate_signal_type(signal_type, candidate_text):
            continue

        state = classify_state(candidate_text)
        if state == "context":
            continue

        candidate["state"] = state
        candidate["score"] = score_candidate(candidate)
        qualified.append(candidate)

    # 5. Deduplicate raw candidates
    qualified = deduplicate_candidates(qualified)

    # 6. Rank
    qualified.sort(key=lambda item: item["score"], reverse=True)

    # 7. Limit per signal type
    type_counts = {}
    final_candidates = []

    for candidate in qualified:
        signal_type = candidate["signal_type"]
        count = type_counts.get(signal_type, 0)
        if count >= MAX_CANDIDATES_PER_TYPE:
            continue
        type_counts[signal_type] = count + 1
        final_candidates.append(candidate)

    final_candidates = final_candidates[:MAX_SIGNALS]
    print(f"Final signal candidates: {len(final_candidates)}")

    # 8. Convert to rich intelligence objects
    rich_signals = []
    normalized_source = normalize_whitespace(text)

    for candidate in final_candidates:
        excerpt = build_excerpt(candidate["text"])

        if len(excerpt) < MIN_EXCERPT_LENGTH:
            continue
        if len(excerpt.split()) < MIN_WORD_COUNT:
            continue

        normalized_excerpt = normalize_whitespace(excerpt)
        if normalized_excerpt not in normalized_source:
            print("[Traceability rejected]", candidate["signal_type"], excerpt[:120])
            continue

        rich_signals.append(
            build_rich_signal(candidate, company_name)
        )

    rich_signals = deduplicate_rich_signals(rich_signals)

    print(f"Rich signals returned: {len(rich_signals)}")

    # Debug preview
    print("\n--- RICH SIGNALS DEBUG ---")
    for i, signal in enumerate(rich_signals[:10], start=1):
        print(f"\n[{i}] {signal['headline']}")
        print("TYPE:", signal["signal_type"])
        print("STATE:", signal["event_state"])
        print("MATERIALITY:", signal["materiality"])
        print("CONFIDENCE:", signal["confidence"])
        print("LOCATION:", signal["location"]["mentions"])
        print("INVESTMENT:", signal["investment"]["values"])
        print("SCALE:", signal["physical_scale"])
        print("TIMELINE:", signal["timeline"])
        print("EXCERPT:", signal["evidence"]["excerpt"][:500])

    return rich_signals


# ============================================================
# EXPANDED LLM CONTEXT RETRIEVAL
# ============================================================

def _llm_event_discovery_candidates(sentences):
    """Find broad event candidates for the LLM path without replacing semantic retrieval.

    The production extractor intentionally favors precision. This helper instead
    adds a recall-oriented lexical pass for secondary events such as capacity
    increases, store/network expansion, augmentation and leadership changes.
    It is deliberately used only by ``extract_evidence_context``.
    """
    candidates = []
    for index, sentence in enumerate(sentences):
        lower = sentence.lower()
        if is_boilerplate(sentence):
            continue

        start = max(0, index - 1)
        end = min(len(sentences), index + 2)
        chunk = " ".join(sentences[start:end])

        for signal_type, patterns in LLM_EVENT_DISCOVERY_PATTERNS.items():
            hits = sum(1 for pattern in patterns if re.search(pattern, lower, re.IGNORECASE))
            if hits < LLM_EVENT_MIN_LEXICAL_SCORE:
                continue

            # Avoid turning generic mentions into candidates unless there is an
            # action/event cue somewhere in the sentence window.
            action_hit = any(
                re.search(rf"\b{re.escape(word)}\b", chunk.lower())
                for word in ACTION_WORDS
            )
            if not action_hit and signal_type not in {"acquisition", "merger", "leadership_change", "plant_commissioning"}:
                continue

            candidate = {
                "signal_type": signal_type,
                "text": chunk,
                "sentence_index": index,
                "semantic_similarity": 0.0,
                "lexical_hits": hits,
                "discovery_source": "event_lexical",
            }
            candidate["state"] = classify_state(chunk)
            if candidate["state"] == "context":
                continue
            candidate["score"] = 20 + hits * 4 + linguistic_score(signal_type, chunk)
            candidates.append(candidate)

    # Same sentence can match multiple useful event concepts; keep diversity.
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[:LLM_EVENT_MAX_LEXICAL_CANDIDATES]


def extract_evidence_context(
    text,
    company_name="",
    context_radius=30,
    max_candidates=120,
    max_context_chars=700_000,
):
    """Prepare richer context for an LLM reasoning layer.

    The production ``extract_evidence`` path remains unchanged.
    Semantic retrieval still uses the original previous/current/next
    sentence windows. Once a relevant candidate is found, this function
    expands the surrounding source context so an LLM can reason about
    event state, conditions, dates, locations, scale, and supporting facts.
    """
    if not text:
        return []

    sentences = split_into_sentences(text)
    if not sentences:
        return []

    # Preserve the existing semantic retrieval behavior, then union it with a
    # recall-oriented event vocabulary pass. This prevents secondary events from
    # disappearing simply because their wording is not close to one semantic
    # signal definition.
    chunks = build_chunks(sentences)
    semantic = semantic_candidates(chunks)
    lexical = _llm_event_discovery_candidates(sentences)
    candidates = semantic + lexical

    qualified = []
    for candidate in candidates:
        candidate_text = candidate["text"]
        signal_type = candidate["signal_type"]
        semantic_similarity = candidate["semantic_similarity"]

        if is_boilerplate(candidate_text):
            continue
        if (
            semantic_similarity < STRONG_SEMANTIC_THRESHOLD
            and linguistic_score(signal_type, candidate_text) < 5
        ):
            continue
        if not validate_signal_type(signal_type, candidate_text):
            continue

        state = classify_state(candidate_text)
        if state == "context":
            continue

        candidate["state"] = state
        candidate["score"] = score_candidate(candidate)
        qualified.append(candidate)

    qualified = deduplicate_candidates(qualified)
    qualified.sort(key=lambda item: item["score"], reverse=True)

    selected = []
    type_counts = {}
    for candidate in qualified:
        signal_type = candidate["signal_type"]
        count = type_counts.get(signal_type, 0)
        if count >= 24:
            continue
        type_counts[signal_type] = count + 1
        selected.append(candidate)
        if len(selected) >= max_candidates:
            break

    packets = []
    total_chars = 0
    seen_contexts = set()

    for candidate in selected:
        center = candidate["sentence_index"]
        start = max(0, center - context_radius)
        end = min(len(sentences), center + context_radius + 1)
        expanded_context = normalize_whitespace(" ".join(sentences[start:end]))

        dedupe_key = expanded_context.lower()
        if dedupe_key in seen_contexts:
            continue
        seen_contexts.add(dedupe_key)

        packet = (
            f"[Candidate {len(packets) + 1}]\\n"
            f"Existing type hint: {candidate['signal_type']}\\n"
            f"Existing state hint: {candidate['state']}\\n"
            f"Semantic similarity: {candidate['semantic_similarity']:.3f}\\n"
            f"Candidate score: {candidate['score']:.2f}\\n"
            f"Source sentence index: {center + 1}\\n"
            f"Expanded source context:\\n{expanded_context}\\n"
        )

        if total_chars + len(packet) > max_context_chars:
            break

        packets.append(packet)
        total_chars += len(packet)

    return packets


# ============================================================
# DATABASE INTEGRATION
# ============================================================

def _get_company_name(document):
    """Best-effort company name lookup without changing Document model."""
    metadata = document.metadata_json or {}

    if isinstance(metadata, dict):
        for key in ("company_name", "company", "name"):
            value = metadata.get(key)
            if value:
                return str(value)

    return document.title or ""


def rich_signal_to_evidence(signal, document):
    """Convert one rich extractor signal into the SQLAlchemy Evidence model."""
    evidence_data = signal.get("evidence") or {}
    excerpt = evidence_data.get("excerpt")
    signal_type = signal.get("signal_type")

    if not excerpt or not signal_type:
        return None

    return Evidence(
        document_id=document.id,
        evidence_type=signal_type,
        event_state=signal.get("event_state"),
        headline=signal.get("headline"),
        summary=signal.get("summary"),
        why_it_matters=signal.get("why_it_matters"),
        company=signal.get("company") or _get_company_name(document),
        statement=signal.get("summary") or excerpt,
        excerpt=excerpt,
        location_hint=(
            f"sentence:{evidence_data.get('sentence_index')}"
            if evidence_data.get("sentence_index") is not None
            else None
        ),
        location=signal.get("location"),
        investment=signal.get("investment"),
        physical_scale=signal.get("physical_scale"),
        timeline=signal.get("timeline"),
        physical_consequence=signal.get("physical_consequence"),
        supporting_facts=signal.get("supporting_facts"),
        confidence=signal.get("confidence"),
        semantic_similarity=signal.get("semantic_similarity"),
        score=signal.get("score"),
        materiality=signal.get("materiality"),
        source_quality=signal.get("source_quality", "annual_report"),
        validation_status="pending",
    )


def extract_and_store_evidence(document):
    """Extract rich signals and return new Evidence ORM objects.

    The objects are intentionally NOT committed here. The route owns the
    transaction so a failure can roll back the complete extraction operation.
    """
    if not document:
        return [], 0

    if not document.raw_text:
        return [], 0

    company_name = _get_company_name(document)

    rich_signals = extract_evidence(
        document.raw_text,
        company_name=company_name,
    )

    created_evidence = []
    skipped_duplicates = 0

    for signal in rich_signals:
        evidence = rich_signal_to_evidence(
            signal,
            document,
        )

        if evidence is None:
            continue

        existing = Evidence.query.filter_by(
            document_id=document.id,
            evidence_type=evidence.evidence_type,
            excerpt=evidence.excerpt,
        ).first()

        if existing:
            skipped_duplicates += 1
            continue

        created_evidence.append(evidence)

    return created_evidence, skipped_duplicates
