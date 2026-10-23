from datetime import datetime, timezone

from applications.extentions import db


class Evidence(db.Model):
    __tablename__ = "evidence"

    __table_args__ = (
        db.UniqueConstraint(
            "document_id",
            "evidence_type",
            "excerpt",
            name="uq_evidence_document_type_excerpt"
        ),
    )

    # ========================================================
    # IDENTITY
    # ========================================================

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    document_id = db.Column(
        db.Integer,
        db.ForeignKey("documents.id"),
        nullable=False,
    )

    evidence_type = db.Column(
        db.String(100),
        nullable=False,
        index=True,
    )

    # ========================================================
    # EVENT INTERPRETATION
    # ========================================================

    event_state = db.Column(
        db.String(50),
        nullable=True,
        index=True,
    )

    headline = db.Column(
        db.String(1000),
        nullable=True,
    )

    summary = db.Column(
        db.Text,
        nullable=True,
    )

    why_it_matters = db.Column(
        db.Text,
        nullable=True,
    )

    # ========================================================
    # COMPANY
    # ========================================================

    company = db.Column(
        db.String(500),
        nullable=True,
        index=True,
    )

    # ========================================================
    # ORIGINAL EVIDENCE / TRACEABILITY
    # ========================================================

    statement = db.Column(
        db.Text,
        nullable=False,
    )

    excerpt = db.Column(
        db.Text,
        nullable=True,
    )

    location_hint = db.Column(
        db.String(500),
        nullable=True,
    )

    # ========================================================
    # STRUCTURED BUSINESS DETAILS
    # ========================================================
    #
    # JSON columns are used because these fields can contain
    # multiple values and their structure may evolve.
    #
    # Example:
    #
    # location = {
    #     "mentions": ["Panoli", "Gujarat"]
    # }
    #
    # investment = {
    #     "values": ["₹20–21 billion"]
    # }
    #
    # physical_scale = [
    #     "125,000 sq m",
    #     "16 production blocks"
    # ]
    #
    # ========================================================

    location = db.Column(
        db.JSON,
        nullable=True,
    )

    investment = db.Column(
        db.JSON,
        nullable=True,
    )

    physical_scale = db.Column(
        db.JSON,
        nullable=True,
    )

    timeline = db.Column(
        db.JSON,
        nullable=True,
    )

    physical_consequence = db.Column(
        db.JSON,
        nullable=True,
    )

    supporting_facts = db.Column(
        db.JSON,
        nullable=True,
    )

    # ========================================================
    # INTELLIGENCE / SCORING
    # ========================================================

    confidence = db.Column(
        db.Float,
        nullable=True,
        index=True,
    )

    semantic_similarity = db.Column(
        db.Float,
        nullable=True,
    )

    score = db.Column(
        db.Float,
        nullable=True,
        index=True,
    )

    materiality = db.Column(
        db.Float,
        nullable=True,
        index=True,
    )

    source_quality = db.Column(
        db.String(100),
        nullable=True,
    )

    # ========================================================
    # VALIDATION
    # ========================================================

    source_reliability = db.Column(
        db.Float,
        nullable=False,
        default=0.5,
    )

    directness = db.Column(
        db.Float,
        nullable=False,
        default=0.5,
    )

    recency = db.Column(
        db.Float,
        nullable=False,
        default=0.5,
    )

    corroboration = db.Column(
        db.Float,
        nullable=False,
        default=0.0,
    )

    validation_status = db.Column(
        db.String(50),
        nullable=False,
        default="unvalidated",
        index=True,
    )

    validation_reason = db.Column(
        db.Text,
        nullable=True,
    )

    validation_notes = db.Column(
        db.Text,
        nullable=True,
    )

    # ========================================================
    # METADATA
    # ========================================================

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ========================================================
    # RELATIONSHIP
    # ========================================================

    document = db.relationship(
        "Document",
        back_populates="evidence",
    )

    # ========================================================
    # REPRESENTATION
    # ========================================================

    def __repr__(self):
        return (
            f"<Evidence "
            f"{self.id} "
            f"{self.evidence_type} "
            f"{self.event_state}>"
        )