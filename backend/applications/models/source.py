from datetime import datetime, timezone
from applications.extentions import db

class Source(db.Model):
    __tablename__ = "sources"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    source_type = db.Column(db.String(100), nullable=False)
    base_url = db.Column(db.String(1000), nullable=False)
    access_method = db.Column(db.String(50), nullable=False)
    authority_level = db.Column(db.String(50), nullable=False, default="secondary")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    documents = db.relationship("Document", back_populates="source", lazy=True)

    def __repr__(self):
        return f"<Source {self.name}"