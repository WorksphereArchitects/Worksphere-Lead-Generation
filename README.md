# WorkSphere Market Intelligence & Opportunity Signal Engine

WorkSphere Market Intelligence & Opportunity Signal Engine is a market-intelligence system designed to identify business events and market signals that may create future architectural, workplace, industrial, infrastructure, or related project opportunities.

The central idea is:

> **Do not search only for projects that have already appeared. Search for the business events that are likely to create those projects.**

---

## 1. Project Overview

The final system is intended to continuously monitor market information, identify meaningful business changes, build evidence around those changes, infer potential projects, identify relevant decision-makers, and support business development before conventional project opportunities become publicly visible.

The intended intelligence flow is:

```text
INTERNET
   ↓
DATA INGESTION
   ↓
RAW DATA
   ↓
NORMALIZATION
   ↓
DEDUPLICATION
   ↓
EVIDENCE EXTRACTION
   ↓
EVIDENCE VALIDATION
   ↓
SIGNALS
   ↓
COMPANY INTELLIGENCE
   ↓
PROJECT INTELLIGENCE
   ↓
DECISION-MAKER INTELLIGENCE
   ↓
COMPETITIVE INTELLIGENCE
   ↓
OPPORTUNITY
   ↓
BD VALIDATION
   ↓
LEAD
```

The current implementation covers the **data ingestion and validated evidence foundation** of this architecture.

The higher-level intelligence layers are planned for subsequent development.

---

# 2. Core Architecture

![WorkSphere Final Architecture](docs/architecture/worksphere-final-architecture.png)

The final product is organized around five intelligence layers.

## Layer 1 — Market Intelligence

The Market Intelligence layer gathers information from relevant external sources.

Potential source categories include:

- Company websites
- Annual reports
- Investor presentations
- Stock exchange announcements
- Government portals
- Tender portals
- Environmental approval databases
- Company career/job postings
- News sources
- Industry publications
- Corporate databases
- Professional networks
- Procurement databases

The purpose of this layer is to establish a broad and continuously updated information base.

```text
External Sources
       ↓
Data Collection
       ↓
Raw Documents
       ↓
Validated Evidence
```

---

## Layer 2 — Company Intelligence

The Company Intelligence layer builds a company-level understanding from validated market evidence.

The intended company story includes:

- Ambition
- Tailwinds
- Headwinds
- Commitment
- Physical tracking
- Relevant business changes
- Opportunity hypotheses

The intended progression is:

```text
Company
   ↓
Business Events
   ↓
Validated Evidence
   ↓
Company Story
```

The system should eventually identify companies experiencing business changes that may create relevant opportunities.

---

## Layer 3 — Project Intelligence

The Project Intelligence layer determines what type of project may emerge from a company's business changes.

### Industrial example

```text
Demand / Product Growth
        ↓
Capacity Requirement
        ↓
Capital Expenditure
        ↓
Land / Approvals
        ↓
Facility Formation
        ↓
Potential Industrial Project
```

### Workplace example

```text
Business Growth
        ↓
Employee Growth
        ↓
Hiring
        ↓
New City / Unit / GCC
        ↓
Office Requirement
        ↓
Potential Workplace Project
```

The project intelligence layer will eventually estimate:

- Project type
- Project stage
- Likely timeframe
- Physical consequence
- WorkSphere fit
- Opportunity hypothesis
- Current maturity

---

## Layer 4 — Decision-Maker Intelligence

The Decision-Maker Intelligence layer connects identified opportunities to relevant stakeholders.

Potential roles include:

- CEO
- CFO
- COO
- CHRO
- Plant Head
- Business Unit Head
- Real Estate Head
- Facilities Head
- Procurement
- Project leadership
- Other relevant decision-makers and influencers

The objective is to identify the people who may influence or decide the potential opportunity.

---

## Layer 5 — Competitive Intelligence

The Competitive Intelligence layer provides market and competitive context.

It is intended to identify:

- Existing consultants
- Existing relationships
- Competitors
- Relevant WorkSphere capabilities
- Competitive positioning
- Potential differentiation

---

# 3. Current Project State

The current implementation has completed the **data ingestion and evidence foundation**.

The implemented pipeline is:

```text
Source
   ↓
Document
   ↓
Evidence Extraction
   ↓
Evidence Validation
   ↓
Evidence Retrieval
   ↓
Evidence Deduplication
   ↓
Evidence Provenance
```

## Currently Implemented

- Source registration
- Source persistence
- Source → Document relationship
- HTTP document ingestion
- HTML parsing
- Document title extraction
- Raw text extraction
- Canonical/final URL capture
- HTTP metadata storage
- SHA-256 document hashing
- Document duplicate detection
- Document retrieval APIs
- Deterministic evidence extraction
- Candidate evidence classification
- Evidence validation
- Evidence validation reasons
- Evidence retrieval APIs
- Evidence filtering by validation status
- Evidence provenance
- Evidence location hints
- Application-level evidence deduplication
- Database-level evidence uniqueness
- PostgreSQL persistence
- Database migrations

---

## Current Evidence Categories

The deterministic evidence extractor currently recognizes:

```text
investment
capacity_expansion
facility_expansion
new_facility
hiring
leadership_change
acquisition
merger
technology_transformation
sustainability
```

These are currently **evidence classifications**.

They should not be interpreted as confirmed projects, signals, or opportunities by themselves.

---

# 4. What the Current Project Does

The current system can take an external source, retrieve its content, store the source document, extract candidate evidence, validate that evidence against the original document, and maintain a provenance chain.

For example:

```text
Tata Motors Website
        ↓
Source Record
        ↓
Fetch Webpage
        ↓
Store Document
        ↓
Extract Relevant Text
        ↓
Identify Evidence Candidates
        ↓
Validate Candidates
        ↓
Store Validated Evidence
```

The provenance chain is:

```text
Evidence
   ↓
Document
   ↓
Source
   ↓
Original URL
```

This allows the system to answer:

> What evidence was found, where was it found, and which source document supports it?

---

## Important Distinction

The current system does **not** yet conclude that a company has a project or opportunity simply because evidence exists.

For example:

```text
"commitment to a zero-emission future"
```

may be valid sustainability evidence, but it does not independently prove:

```text
New Factory
Investment
Construction Project
RFP
```

That interpretation belongs to the future signal and intelligence layers.

The current system deliberately maintains the distinction:

```text
FACT
  ↓
EVIDENCE
  ↓
SIGNAL
  ↓
INFERENCE
  ↓
OPPORTUNITY HYPOTHESIS
  ↓
CLIENT VALIDATION
  ↓
LEAD
```

---

# 5. Current Architecture

## Repository Structure

```text
worksphere/
│
├── backend/
│   │
│   ├── app.py
│   │
│   ├── applications/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── extentions.py
│   │   │
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── source.py
│   │   │   ├── document.py
│   │   │   └── evidence.py
│   │   │
│   │   ├── routes/
│   │   │   ├── sources.py
│   │   │   ├── documents.py
│   │   │   └── evidence.py
│   │   │
│   │   └── services/
│   │       ├── fetcher.py
│   │       ├── evidence_extractor.py
│   │       └── evidence_validator.py
│   │
│   ├── migrations/
│   ├── requirements.txt
│   ├── .env
│   └── venv/
│
├── frontend/
│
└── .gitignore
```

> **Note:** `extentions.py` is the current filename used by the implementation. Although `extensions.py` would normally be preferred spelling, it should not be renamed without updating all imports.

---

# 6. Current Data Model

## Source

Represents an external information source.

```text
Source
------
id
name
source_type
base_url
access_method
authority_level
is_active
notes
created_at
```

---

## Document

Represents a fetched source document or webpage.

```text
Document
--------
id
source_id
url
canonical_url
title
published_at
fetched_at
content_type
http_status
content_hash
raw_text
metadata_json
```

---

## Evidence

Represents candidate or validated evidence extracted from a document.

```text
Evidence
--------
id
document_id
evidence_type
statement
excerpt
location_hint
validation_status
validation_reason
```

---

## Relationships

```text
Source
  │
  │ 1:N
  ▼
Document
  │
  │ 1:N
  ▼
Evidence
```

Evidence does not need to duplicate `source_id`.

The provenance chain is resolved through:

```text
Evidence.document_id
        ↓
Document.source_id
        ↓
Source
```

---

# 7. Technology Stack

## Backend

- Python
- Flask 3.1.2
- Flask-SQLAlchemy 3.1.1
- Flask-Migrate 4.1.0
- SQLAlchemy
- PostgreSQL
- psycopg 3.2.10
- python-dotenv
- Requests
- BeautifulSoup4

## Database

PostgreSQL is used as the primary relational database.

Current database tables:

```text
sources
documents
evidence
alembic_version
```

## Frontend

A separate `frontend/` directory exists.

The frontend implementation is not part of the current completed backend/evidence milestone. No specific frontend framework is currently established by the implementation.

The intended architecture is:

```text
Frontend
   ↓
REST API
   ↓
Flask Backend
   ↓
PostgreSQL
```

---

# 8. Backend Setup

## Prerequisites

Install:

- Python 3.x
- PostgreSQL
- Git

Verify:

```powershell
python --version
psql --version
git --version
```

---

## Clone the Repository

```powershell
git clone https://github.com/AtharvaGGourshete/Lead-Discovery-Freelance
cd worksphere
```

---

## Create Virtual Environment

From the backend directory:

```powershell
cd backend
python -m venv venv
```

Activate on Windows PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
```

---

## Install Dependencies

```powershell
pip install -r requirements.txt
```

Current requirements:

```text
Flask==3.1.2
Flask-SQLAlchemy==3.1.1
Flask-Migrate==4.1.0
psycopg[binary]==3.2.10
python-dotenv==1.1.1
requests
beautifulsoup4
```

---

# 9. PostgreSQL Setup

## Create Database

Open PostgreSQL:

```powershell
psql -U postgres
```

Create the database:

```sql
CREATE DATABASE worksphere;
```

Connect to it:

```sql
\c worksphere
```

Verify:

```sql
\dt
```

After migrations, the database should contain:

```text
alembic_version
documents
evidence
sources
```

---

# 10. Environment Configuration

Create:

```text
backend/.env
```

Add:

```env
DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/worksphere
```

Replace:

```text
YOUR_PASSWORD
```

with the local PostgreSQL password.

Do **not** commit `.env` to GitHub.

The repository should contain an example environment file if required:

```text
.env.example
```

without real credentials.

---

# 11. Database Migrations

From the `backend/` directory:

```powershell
python -m flask db upgrade
```

To create a migration after modifying models:

```powershell
python -m flask db migrate -m "migration message"
```

Then:

```powershell
python -m flask db upgrade
```

### Windows Note

The current development environment may block direct execution of:

```powershell
flask
```

through `flask.exe`.

Therefore, use:

```powershell
python -m flask
```

instead.

---

# 12. Start Backend

From:

```text
backend/
```

run:

```powershell
python -m flask run
```

Expected:

```text
Running on http://127.0.0.1:5000
```

Base API URL:

```text
http://127.0.0.1:5000
```

---

# 13. Frontend Setup

The frontend is a Vite application in `frontend/`. Install dependencies and run the development server from that directory:

```powershell
cd frontend
npm install
npm run dev
```

## Production Deployment (Render + Vercel)

The Vite frontend reads `VITE_API_BASE_URL` at build time. In the Vercel project's environment variables, set it to the Render backend URL **including `/api`**, for example:

```text
VITE_API_BASE_URL=https://your-render-service.onrender.com/api
```

Redeploy the Vercel project after changing the variable. The frontend defaults to the current WorkSphere Render API URL, so set this variable when using a different Render service or custom backend domain.

The backend restricts browser requests using `CORS_ORIGINS`. The production Vercel origin `https://worksphere-lead-generation.vercel.app` is always allowed. In the Render service's environment variables, list any additional site origins, with no path, separated by commas if needed:

```text
CORS_ORIGINS=https://your-vercel-project.vercel.app
```

Include any Vercel custom domain or preview origin that should be allowed. Keep the scheme (`https://`) and do not add a trailing slash. When `CORS_ORIGINS` is unset, the backend also allows the two local development origins.

After saving Render variables, restart/redeploy the backend. The frontend URL must point to the API's `/api` base; the backend CORS value must be the frontend's origin, not the backend URL.

---

# 14. API Reference

Base URL:

```text
http://127.0.0.1:5000
```

---

## 14.1 Create Source

### Endpoint

```http
POST /api/sources
```

### Headers

```http
Content-Type: application/json
```

### Request Body

```json
{
    "name": "Tata Motors",
    "source_type": "company_website",
    "base_url": "https://www.tatamotors.com",
    "access_method": "http",
    "authority_level": "primary",
    "notes": "Tata Motors official company website"
}
```

### Expected Response

```text
201 Created
```

Example:

```json
{
    "id": 1,
    "name": "Tata Motors",
    "source_type": "company_website",
    "base_url": "https://www.tatamotors.com",
    "access_method": "http",
    "authority_level": "primary",
    "is_active": true,
    "notes": "Tata Motors official company website"
}
```

---

## 14.2 List Documents

### Endpoint

```http
GET /api/documents
```

### Request Body

None.

### Purpose

Returns a lightweight list of stored documents.

`raw_text` is intentionally excluded from this response.

### Example Response

```json
[
    {
        "id": 1,
        "source_id": 1,
        "url": "https://www.tatamotors.com",
        "canonical_url": "https://www.tatamotors.com/",
        "title": "Tata Motors",
        "published_at": null,
        "fetched_at": "2026-09-25T00:00:00+00:00",
        "content_type": "text/html; charset=UTF-8",
        "http_status": 200,
        "content_hash": "..."
    }
]
```

---

## 14.3 Create / Ingest Document

### Endpoint

```http
POST /api/documents
```

### Headers

```http
Content-Type: application/json
```

### Request Body

```json
{
    "source_id": 1,
    "url": "https://www.tatamotors.com"
}
```

### Expected Response

```text
201 Created
```

### Processing

The backend:

1. Validates `source_id`
2. Validates the URL
3. Checks that the source exists
4. Checks that the source is active
5. Fetches the URL
6. Validates the HTTP response
7. Validates HTML content
8. Extracts the page title
9. Extracts readable page text
10. Captures the canonical/final URL
11. Captures HTTP metadata
12. Calculates a SHA-256 content hash
13. Checks for duplicate document content
14. Stores the document in PostgreSQL

---

## 14.4 Get Document

### Endpoint

```http
GET /api/documents/{document_id}
```

### Example

```http
GET /api/documents/1
```

### Request Body

None.

### Example Response

```json
{
    "id": 1,
    "source_id": 1,
    "url": "https://www.tatamotors.com",
    "canonical_url": "https://www.tatamotors.com/",
    "title": "Tata Motors",
    "published_at": null,
    "fetched_at": "2026-09-25T00:00:00+00:00",
    "content_type": "text/html; charset=UTF-8",
    "http_status": 200,
    "content_hash": "...",
    "raw_text": "...",
    "metadata_json": {
        "content_length": 94652
    }
}
```

---

## 14.5 Extract Evidence

### Endpoint

```http
POST /api/documents/{document_id}/extract-evidence
```

### Example

```http
POST /api/documents/1/extract-evidence
```

### Request Body

None.

### Purpose

Reads the stored document's `raw_text` and extracts candidate evidence using deterministic pattern matching.

### Example Response

```json
{
    "document_id": 1,
    "evidence_count": 3,
    "duplicates_skipped": 0,
    "message": "Evidence extracted successfully",
    "evidence": [
        {
            "id": 1,
            "evidence_type": "sustainability",
            "statement": "Example evidence statement",
            "excerpt": "Example evidence statement",
            "validation_status": "pending"
        }
    ]
}
```

### Evidence Status

Newly extracted evidence starts as:

```text
pending
```

It must be validated before being treated as validated evidence.

---

## 14.6 Validate Evidence

### Endpoint

```http
POST /api/documents/{document_id}/validate-evidence
```

### Example

```http
POST /api/documents/1/validate-evidence
```

### Request Body

None.

### Validation Checks

The validation service checks:

- Source document exists
- Document URL exists
- Document contains raw text
- Evidence excerpt exists
- Excerpt meets minimum length
- Excerpt contains sufficient words
- Excerpt exists in the original document
- Evidence type is recognized

### Example Response

```json
{
    "document_id": 1,
    "validated_count": 3,
    "rejected_count": 0,
    "evidence": [
        {
            "id": 1,
            "evidence_type": "sustainability",
            "statement": "Example evidence statement",
            "excerpt": "Example evidence statement",
            "validation_status": "validated",
            "validation_reason": "Evidence is traceable to the source document, contains sufficient content, and uses a recognized evidence type."
        }
    ]
}
```

---

## 14.7 Get Evidence for Document

### Endpoint

```http
GET /api/documents/{document_id}/evidence
```

### Example

```http
GET /api/documents/1/evidence
```

### Request Body

None.

### Optional Query Parameter

```text
validation_status
```

Examples:

```http
GET /api/documents/1/evidence?validation_status=pending
```

```http
GET /api/documents/1/evidence?validation_status=validated
```

### Example Response

```json
{
    "document_id": 1,
    "count": 3,
    "evidence": [
        {
            "id": 1,
            "evidence_type": "sustainability",
            "statement": "Example evidence statement",
            "excerpt": "Example evidence statement",
            "location_hint": "sentence:42",
            "validation_status": "validated",
            "validation_reason": "Evidence is traceable to the source document, contains sufficient content, and uses a recognized evidence type."
        }
    ]
}
```

---

## 14.8 List Evidence

### Endpoint

```http
GET /api/evidence
```

### Request Body

None.

### Optional Query Parameter

```text
validation_status
```

Examples:

```http
GET /api/evidence?validation_status=pending
```

```http
GET /api/evidence?validation_status=validated
```

### Example Response

```json
{
    "count": 3,
    "evidence": [
        {
            "id": 1,
            "document_id": 1,
            "evidence_type": "sustainability",
            "statement": "Example evidence statement",
            "excerpt": "Example evidence statement",
            "location_hint": "sentence:42",
            "validation_status": "validated",
            "validation_reason": "Evidence is traceable to the source document, contains sufficient content, and uses a recognized evidence type."
        }
    ]
}
```

---

## 14.9 Get Individual Evidence

### Endpoint

```http
GET /api/evidence/{evidence_id}
```

### Example

```http
GET /api/evidence/1
```

### Request Body

None.

### Example Response

```json
{
    "id": 1,
    "document_id": 1,
    "evidence_type": "sustainability",
    "statement": "Example evidence statement",
    "excerpt": "Example evidence statement",
    "location_hint": "sentence:42",
    "validation_status": "validated",
    "validation_reason": "Evidence is traceable to the source document, contains sufficient content, and uses a recognized evidence type.",
    "provenance": {
        "document_id": 1,
        "source_id": 1,
        "source_name": "Tata Motors",
        "source_type": "company_website",
        "document_url": "https://www.tatamotors.com",
        "canonical_url": "https://www.tatamotors.com/",
        "location_hint": "sentence:42"
    }
}
```

---

# 15. API Summary

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/sources` | Register a source |
| `GET` | `/api/documents` | List documents |
| `POST` | `/api/documents` | Fetch and store a document |
| `GET` | `/api/documents/{id}` | Retrieve a document |
| `POST` | `/api/documents/{id}/extract-evidence` | Extract candidate evidence |
| `POST` | `/api/documents/{id}/validate-evidence` | Validate pending evidence |
| `GET` | `/api/documents/{id}/evidence` | Get evidence belonging to a document |
| `GET` | `/api/evidence` | List evidence |
| `GET` | `/api/evidence/{id}` | Get evidence and provenance |

---

# 16. HTTP Status Codes

The current API uses standard HTTP status codes.

| Status | Meaning |
|---|---|
| `200` | Successful request |
| `201` | Resource successfully created |
| `400` | Invalid request |
| `404` | Resource not found |
| `409` | Duplicate resource |
| `502` | External source fetch failure |

---

# 17. Data Processing Pipeline

The current implementation follows this pipeline:

```text
                         INTERNET
                            │
                            ▼
                    SOURCE REGISTRATION
                            │
                            ▼
                    HTTP DOCUMENT FETCH
                            │
                            ▼
                      RAW DOCUMENT
                            │
                            ▼
                  DOCUMENT NORMALIZATION
                            │
                            ▼
                    CONTENT HASHING
                            │
                            ▼
                    DUPLICATE CHECK
                            │
                            ▼
                    DOCUMENT STORAGE
                            │
                            ▼
                   EVIDENCE EXTRACTION
                            │
                            ▼
                   CANDIDATE EVIDENCE
                            │
                            ▼
                   EVIDENCE VALIDATION
                            │
                            ▼
                   VALIDATED EVIDENCE
                            │
                            ▼
                       PROVENANCE
                            │
                            ▼
                    EVIDENCE RETRIEVAL
```

---

# 18. Data Integrity Principles

## Raw Data Is Preserved

The original fetched document text is stored in:

```text
Document.raw_text
```

The raw source document therefore remains available for downstream verification.

---

## Evidence Is Traceable

Every evidence record references the document from which it was extracted.

```text
Evidence
   ↓
Document
```

---

## Evidence Is Not Automatically a Signal

A piece of evidence does not automatically represent a business trigger, project, or opportunity.

The system deliberately separates:

```text
Evidence
   ↓
Signal
   ↓
Inference
```

---

## Application-Level Deduplication

The extractor checks whether the same evidence already exists before creating a new record.

The current uniqueness logic is based on:

```text
document_id
+
evidence_type
+
excerpt
```

---

## Database-Level Deduplication

The database also enforces evidence uniqueness using:

```text
document_id
+
evidence_type
+
excerpt
```

This provides an additional layer of protection against duplicate records.

---

## Evidence Must Be Source-Backed

Validated evidence must contain an excerpt that exists in the original document.

This prevents an extracted statement from becoming validated evidence without source support.

---

# 19. Database Reset for Testing

For development/testing, all application records can be deleted while preserving the database schema and migrations.

Connect to PostgreSQL:

```powershell
psql -U postgres -d worksphere
```

Run:

```sql
TRUNCATE TABLE evidence, documents, sources RESTART IDENTITY CASCADE;
```

This:

- Deletes all evidence
- Deletes all documents
- Deletes all sources
- Resets their identity sequences
- Preserves the database tables
- Preserves migrations

The next records will therefore start from:

```text
Source   → ID 1
Document → ID 1
Evidence → ID 1
```

Verify:

```sql
SELECT COUNT(*) FROM sources;
SELECT COUNT(*) FROM documents;
SELECT COUNT(*) FROM evidence;
```

Expected:

```text
0
0
0
```

> Do not drop the tables or delete the `alembic_version` table when performing a normal test reset.

---

# 20. Current Limitations

The following capabilities are intentionally outside the current implementation:

- Automated web crawling at scale
- Scheduled crawling
- Source-specific crawling strategies
- PDF extraction pipeline
- News API integrations
- Government portal integrations
- Stock exchange integrations
- Tender portal integrations
- LLM-based evidence extraction
- Signal constellation detection
- Company entity resolution
- Company Intelligence
- Project Intelligence
- Opportunity scoring
- Decision-Maker Intelligence
- Competitive Intelligence
- Automated outreach
- BD workflow
- Lead conversion
- Frontend intelligence dashboard

These capabilities belong to subsequent development stages.

---

# 21. Development Direction

The next major implementation stage is **Signal Detection**.

The intended progression is:

```text
Step 4
Validated Evidence
        ↓
Step 5
Signal Detection
        ↓
Company Intelligence
        ↓
Project Intelligence
        ↓
Decision-Maker Intelligence
        ↓
Competitive Intelligence
        ↓
Opportunity Intelligence
        ↓
BD Validation
        ↓
Lead
```

The fundamental architectural principle is:

> **Evidence must come before inference.**

The system should maintain a clear distinction between:

```text
FACT
  ↓
EVIDENCE
  ↓
SIGNAL
  ↓
INFERENCE
  ↓
OPPORTUNITY HYPOTHESIS
  ↓
CLIENT VALIDATION
  ↓
LEAD
```

This separation is fundamental to building an auditable Market Intelligence system.