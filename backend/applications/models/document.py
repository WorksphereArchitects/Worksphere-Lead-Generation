from datetime import datetime, timezone

from applications.extentions import db


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer,db.ForeignKey("sources.id"),nullable=False)
    url = db.Column(db.String(2000),nullable=False)
    canonical_url = db.Column(db.String(2000))
    title = db.Column(db.String(1000))
    published_at = db.Column(db.DateTime(timezone=True))
    fetched_at = db.Column(db.DateTime(timezone=True),nullable=False,default=lambda: datetime.now(timezone.utc))
    content_type = db.Column(db.String(200))
    http_status = db.Column(db.Integer)
    content_hash = db.Column(db.String(64),nullable=False,unique=True,index=True)
    raw_text = db.Column(db.Text)
    metadata_json = db.Column(db.JSON)

    source = db.relationship("Source", back_populates="documents")
    evidence = db.relationship("Evidence", back_populates="document", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Document {self.title}>"