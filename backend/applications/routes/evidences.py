from flask import jsonify, Blueprint, request
from applications.models.evidence import Evidence

evidences = Blueprint("evidences", __name__, url_prefix="/api/evidences")

@evidences.route("", methods=["GET"])
def list_evidence():
    validation_status = request.args.get("validation_status")

    query = Evidence.query

    if validation_status:
        query = query.filter_by(validation_status=validation_status)

    records = query.order_by(Evidence.id.desc()).all()

    return jsonify({
        "count": len(records),
        "evidence": [
            {
                "id": item.id,
                "document_id": item.document_id,
                "evidence_type": item.evidence_type,
                "statement": item.statement,
                "excerpt": item.excerpt,
                "location_hint": item.location_hint,
                "validation_status": item.validation_status,
                "validation_reason": item.validation_reason
            }
            for item in records
        ]
    }), 200

@evidences.route("/<int:evidence_id>", methods=["GET"])
def get_evidence(evidence_id):
    item = Evidence.query.get(evidence_id)
    source = item.document.source
    if not item:
        return jsonify({
            "error": "Evidence not found"
        }), 404

    return jsonify({
        "id": 12,
        "evidence_type": "sustainability",
        "statement": "...",
        "excerpt": "...",
        "validation_status": "validated",
        "validation_reason": "...",
        "provenance": {
            "document_id": 1,
            "source_id": 1,
            "source_name": "Tata Motors",
            "source_type": "company_website",
            "document_url": "https://www.tatamotors.com",
            "canonical_url": "https://www.tatamotors.com/",
            "location_hint": "sentence:42"
    }
    }), 200