import os

from flask import Flask
from flask_cors import CORS
from applications.config import Config
from applications.extentions import db, migrate
from applications.routes.sources import sources
from applications.routes.documents import documents
from applications.routes.evidences import evidences
from applications.routes.companies_routes import companies
from applications.routes.reports import reports
from applications.routes.company_intelligence import company_intelligence


def create_app():
    app = Flask(__name__)

    production_origin = "https://worksphere-lead-generation.vercel.app"
    configured_origins = [
        origin.strip().rstrip("/")
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    default_origins = (
        ["http://localhost:5173", "http://127.0.0.1:5173"]
        if not configured_origins
        else []
    )
    allowed_origins = [
        production_origin,
        *default_origins,
        *configured_origins,
    ]
    allowed_origins = list(dict.fromkeys(allowed_origins))

    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": allowed_origins
            }
        }
    )

    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    
    app.register_blueprint(sources)
    app.register_blueprint(documents)
    app.register_blueprint(evidences)
    app.register_blueprint(companies)
    app.register_blueprint(company_intelligence)
    app.register_blueprint(reports)

    return app