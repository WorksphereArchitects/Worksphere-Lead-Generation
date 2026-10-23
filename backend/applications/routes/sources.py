from flask import Blueprint, jsonify, request
from applications.extentions import db
from applications.models.source import Source

sources = Blueprint("sources", __name__, url_prefix="/api/sources")

@sources.route("", methods=["POST"])
def create_source():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Request body is required"}), 400

    required_fields = ["name", "source_type", "base_url"]

    for field in required_fields:
        if not data.get(field):
            return jsonify({"error": f"{field} is required"})

    source = Source(
        name=data["name"],
        source_type=data["source_type"],
        base_url=data["base_url"],
        access_method=data.get("access_method"),
        authority_level=data.get("authority_level"),
        notes=data.get("notes")
    )

    db.session.add(source)
    db.session.commit()

    return jsonify({
        "id": source.id,
        "name": source.name,
        "source_type": source.source_type,
        "base_url": source.base_url,
        "access_method": source.access_method,
        "authority_level": source.authority_level,
        "is_active": source.is_active,
        "notes": source.notes
    }), 201