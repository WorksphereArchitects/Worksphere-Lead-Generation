import requests

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from applications.extentions import db
from applications.models.document import Document
from applications.models.source import Source
from applications.models.evidence import Evidence
from applications.services.fetcher import fetch_url
from applications.services.evidence_extractor import extract_and_store_evidence
from applications.services.evidence_validator import validate_evidence


documents = Blueprint(
    "documents",
    __name__,
    url_prefix="/api/documents",
)


# ============================================================
# DOCUMENT CREATION
# ============================================================

@documents.route("", methods=["POST"])
def create_document():
    data = request.get_json()

    if not data:
        return jsonify({
            "error": "Request body is required"
        }), 400

    source_id = data.get("source_id")
    url = data.get("url")

    if not source_id:
        return jsonify({
            "error": "source_id is required"
        }), 400

    if not url:
        return jsonify({
            "error": "url is required"
        }), 400

    source = db.session.get(Source, source_id)

    if not source:
        return jsonify({
            "error": "Source not found"
        }), 404

    if not source.is_active:
        return jsonify({
            "error": "Source is inactive"
        }), 400

    try:
        fetched_data = fetch_url(url)

    except requests.RequestException as error:
        return jsonify({
            "error": "Failed to fetch URL",
            "details": str(error),
        }), 502

    except ValueError as error:
        return jsonify({
            "error": str(error)
        }), 400

    existing_document = Document.query.filter_by(
        content_hash=fetched_data["content_hash"]
    ).first()

    if existing_document:
        return jsonify({
            "error": "Document already exists",
            "document_id": existing_document.id,
        }), 409

    document = Document(
        source_id=source.id,
        url=fetched_data["url"],
        canonical_url=fetched_data["canonical_url"],
        title=fetched_data["title"],
        content_type=fetched_data["content_type"],
        http_status=fetched_data["http_status"],
        content_hash=fetched_data["content_hash"],
        raw_text=fetched_data["raw_text"],
        metadata_json=fetched_data["metadata_json"],
    )

    try:
        db.session.add(document)
        db.session.commit()

    except IntegrityError:
        db.session.rollback()

        return jsonify({
            "error": "Document already exists"
        }), 409

    return jsonify({
        "id": document.id,
        "source_id": document.source_id,
        "url": document.url,
        "canonical_url": document.canonical_url,
        "title": document.title,
        "fetched_at": document.fetched_at.isoformat(),
        "content_type": document.content_type,
        "http_status": document.http_status,
        "content_hash": document.content_hash,
        "raw_text": document.raw_text,
        "metadata_json": document.metadata_json,
    }), 201


# ============================================================
# LIST DOCUMENTS
# ============================================================

@documents.route("", methods=["GET"])
def get_documents():
    documents_list = Document.query.order_by(
        Document.fetched_at.desc()
    ).all()

    return jsonify([
        {
            "id": document.id,
            "source_id": document.source_id,
            "url": document.url,
            "canonical_url": document.canonical_url,
            "title": document.title,
            "published_at": (
                document.published_at.isoformat()
                if document.published_at
                else None
            ),
            "fetched_at": (
                document.fetched_at.isoformat()
                if document.fetched_at
                else None
            ),
            "content_type": document.content_type,
            "http_status": document.http_status,
            "content_hash": document.content_hash,
        }
        for document in documents_list
    ]), 200


# ============================================================
# GET SINGLE DOCUMENT
# ============================================================

@documents.route("/<int:document_id>", methods=["GET"])
def get_document_by_id(document_id):
    document = db.session.get(Document, document_id)

    if not document:
        return jsonify({
            "error": "Document was not found."
        }), 404

    return jsonify({
        "id": document.id,
        "source_id": document.source_id,
        "url": document.url,
        "canonical_url": document.canonical_url,
        "title": document.title,
        "published_at": (
            document.published_at.isoformat()
            if document.published_at
            else None
        ),
        "fetched_at": (
            document.fetched_at.isoformat()
            if document.fetched_at
            else None
        ),
        "content_type": document.content_type,
        "http_status": document.http_status,
        "content_hash": document.content_hash,
        "raw_text": document.raw_text,
        "metadata_json": document.metadata_json,
    }), 200


# ============================================================
# EXTRACT RICH EVIDENCE
# ============================================================

@documents.route(
    "/<int:document_id>/extract-evidence",
    methods=["POST"],
)
def extract_document_evidence(document_id):
    document = db.session.get(Document, document_id)

    if not document:
        return jsonify({
            "error": "Document not found."
        }), 404

    try:
        created_evidence, skipped_duplicates = (
            extract_and_store_evidence(document)
        )

        # The extractor only creates ORM objects. The route owns the
        # transaction and commits everything together.
        if created_evidence:
            db.session.add_all(created_evidence)

        db.session.commit()

    except Exception as error:
        db.session.rollback()

        return jsonify({
            "error": "Evidence extraction failed",
            "details": str(error),
        }), 500

    if created_evidence:
        message = "Evidence extracted successfully"
    elif skipped_duplicates:
        message = "Evidence detected, but all candidates already exist"
    else:
        message = "No evidence detected"

    return jsonify({
        "document_id": document.id,
        "evidence_count": len(created_evidence),
        "duplicates_skipped": skipped_duplicates,
        "message": message,
        "evidence": [
            serialize_evidence(evidence)
            for evidence in created_evidence
        ],
    }), 200


# ============================================================
# VALIDATE EVIDENCE
# ============================================================

@documents.route(
    "/<int:document_id>/validate-evidence",
    methods=["POST"],
)
def validate_document_evidence(document_id):
    document = db.session.get(Document, document_id)

    if not document:
        return jsonify({
            "error": "Document not found"
        }), 404

    evidence_records = Evidence.query.filter_by(
        document_id=document.id,
        validation_status="pending",
    ).all()

    validated_count = 0
    rejected_count = 0
    results = []

    try:
        for evidence in evidence_records:
            result = validate_evidence(
                evidence,
                document,
            )

            evidence.validation_status = result["status"]
            evidence.validation_reason = result["reason"]

            if result["status"] == "validated":
                validated_count += 1
            else:
                rejected_count += 1

            results.append(
                serialize_evidence(evidence)
            )

        db.session.commit()

    except Exception as error:
        db.session.rollback()

        return jsonify({
            "error": "Evidence validation failed",
            "details": str(error),
        }), 500

    return jsonify({
        "document_id": document.id,
        "validated_count": validated_count,
        "rejected_count": rejected_count,
        "evidence": results,
    }), 200


# ============================================================
# GET DOCUMENT EVIDENCE
# ============================================================

@documents.route(
    "/<int:document_id>/evidence",
    methods=["GET"],
)
def get_document_evidence(document_id):
    document = db.session.get(Document, document_id)

    if not document:
        return jsonify({
            "error": "Document not found"
        }), 404

    validation_status = request.args.get(
        "validation_status"
    )

    query = Evidence.query.filter_by(
        document_id=document.id
    )

    if validation_status:
        query = query.filter_by(
            validation_status=validation_status
        )

    records = query.order_by(
        Evidence.score.desc().nullslast(),
        Evidence.id.asc(),
    ).all()

    return jsonify({
        "document_id": document.id,
        "count": len(records),
        "evidence": [
            serialize_evidence(item)
            for item in records
        ],
    }), 200


# ============================================================
# SERIALIZATION
# ============================================================

def serialize_evidence(evidence):
    """Return the complete rich evidence representation as JSON-safe data."""
    return {
        "id": evidence.id,
        "document_id": evidence.document_id,

        "evidence_type": evidence.evidence_type,
        "event_state": evidence.event_state,

        "headline": evidence.headline,
        "summary": evidence.summary,
        "why_it_matters": evidence.why_it_matters,

        "company": evidence.company,

        "statement": evidence.statement,
        "excerpt": evidence.excerpt,
        "location_hint": evidence.location_hint,

        "location": evidence.location,
        "investment": evidence.investment,
        "physical_scale": evidence.physical_scale,
        "timeline": evidence.timeline,
        "physical_consequence": evidence.physical_consequence,
        "supporting_facts": evidence.supporting_facts,

        "confidence": evidence.confidence,
        "semantic_similarity": evidence.semantic_similarity,
        "score": evidence.score,
        "materiality": evidence.materiality,
        "source_quality": evidence.source_quality,

        "source_reliability": evidence.source_reliability,
        "directness": evidence.directness,
        "recency": evidence.recency,
        "corroboration": evidence.corroboration,

        "validation_status": evidence.validation_status,
        "validation_reason": evidence.validation_reason,
        "validation_notes": evidence.validation_notes,

        "created_at": (
            evidence.created_at.isoformat()
            if evidence.created_at
            else None
        ),
    }
