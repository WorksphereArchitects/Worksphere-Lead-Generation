"""Offline tests for company news discovery and persistence contracts."""

from __future__ import annotations

import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4


# Keep route/service imports from constructing a live Supabase client.
supabase_module = types.ModuleType("applications.services.supabase_client")
supabase_module.supabase = MagicMock(name="supabase")
sys.modules["applications.services.supabase_client"] = supabase_module

from applications import create_app
from applications.routes import company_intelligence as company_routes
from applications.routes import reports as report_routes
from applications.services import discovery, discovery_relevance, news_intelligence
from applications.services import report_ingestion_jobs, report_processing_jobs


class FakeQuery:
    def __init__(self, data=None):
        self.data = data
        self.payload = None
        self.conflict = None

    def insert(self, payload):
        self.payload = payload
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self.payload = payload
        self.conflict = on_conflict
        return self

    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def in_(self, *_args):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        return SimpleNamespace(data=self.data)


class DiscoveryTests(unittest.TestCase):
    def test_feed_text_strips_embedded_anchor_markup_and_decodes_entities(self):
        self.assertEqual(
            discovery.clean_feed_text(
                '<a href="https://news.example/story">Headline</a>&nbsp;'
                '<font color="#6f6f6f">Publisher</font>'
            ),
            "Headline Publisher",
        )

    def test_publication_timestamp_is_normalized_when_valid(self):
        self.assertEqual(
            discovery.normalize_published_at("Tue, 06 Oct 2026 12:30:00 GMT"),
            "2026-10-06T12:30:00+00:00",
        )
        self.assertIsNone(discovery.normalize_published_at("unknown date"))

    def test_rss_parser_keeps_publisher_and_optional_metadata(self):
        response = SimpleNamespace(
            content=(
                b'<rss><channel><item><title>Factory expansion</title>'
                b'<description>Company plans a factory expansion.</description>'
                b'<link>https://publisher.example/story?id=123</link>'
                b'<source url="https://publisher.example">Publisher</source>'
                b'<guid>story-123</guid></item></channel></rss>'
            ),
            raise_for_status=lambda: None,
        )
        with patch.object(discovery.requests, "get", return_value=response):
            entries = discovery.parse_rss_feed("https://news.example/rss")

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["publisher"], "Publisher")
        self.assertEqual(entries[0]["entry_id"], "story-123")
        self.assertIsNone(entries[0]["published_at"])

    def test_bad_xml_is_not_silently_treated_as_empty_news(self):
        response = SimpleNamespace(
            content=b"<rss><item>",
            raise_for_status=lambda: None,
        )
        with patch.object(discovery.requests, "get", return_value=response):
            with self.assertRaises(discovery.ET.ParseError):
                discovery.parse_rss_feed("https://news.example/rss")

    def test_company_discovery_deduplicates_and_uses_available_aliases(self):
        entries = [
            {
                "title": "Aarti Industries announces factory expansion",
                "summary": "A new factory expansion is planned.",
                "url": "https://publisher.example/story?id=abc&utm_source=rss",
            },
            {
                "title": "Duplicate article",
                "summary": "Factory expansion.",
                "url": "https://publisher.example/story?id=abc&fbclid=tracking",
            },
        ]
        with patch.object(discovery, "parse_rss_feed", return_value=entries) as parser:
            result = discovery.discover_company_news(
                {"name": "Aarti Industries Limited", "symbol": "AARTIIND"},
                aliases=["Aarti Industries"],
                days=20,
            )

        self.assertEqual(len(result["articles"]), 1)
        self.assertEqual(result["duplicate_count"], 1)
        self.assertIn("AARTIIND", parser.call_args.args[0])
        self.assertIsNone(result["articles"][0].get("publisher"))

    def test_url_normalization_removes_trackers_but_preserves_article_identity(self):
        normalized = discovery.normalize_url(
            "HTTPS://Publisher.Example/story/?id=one&utm_source=rss&edition=IN#top"
        )
        self.assertEqual(
            normalized,
            "https://publisher.example/story?edition=IN&id=one",
        )
        self.assertNotEqual(
            normalized,
            discovery.normalize_url("https://publisher.example/story?id=two"),
        )
        self.assertEqual(discovery.normalize_url("javascript:alert(1)"), "")


class ClassifierValidationTests(unittest.TestCase):
    def setUp(self):
        self.article = {
            "title": "Aarti Industries announces new factory expansion",
            "summary": "A new factory expansion will add capacity.",
        }
        self.result = {
            "relevant": True,
            "event_types": ["facility_expansion"],
            "company_role": "subject",
            "business_event": True,
            "physical_implication": True,
            "confidence": 0.9,
            "reason": "The company is the subject of the announcement.",
            "events": [{
                "category": "facility_expansion",
                "description": "The company announced a factory expansion.",
                "supporting_excerpt": "Aarti Industries announces new factory expansion",
            }],
        }

    def test_valid_event_requires_source_excerpt(self):
        validated = discovery_relevance.validate_classification_result(
            self.result, self.article
        )
        self.assertEqual(validated["events"][0]["category"], "facility_expansion")

    def test_fabricated_excerpt_is_rejected(self):
        result = {**self.result, "events": [{
            **self.result["events"][0],
            "supporting_excerpt": "The company approved a 500 crore investment.",
        }]}
        with self.assertRaisesRegex(ValueError, "does not match"):
            discovery_relevance.validate_classification_result(result, self.article)

    def test_unsupported_category_is_rejected(self):
        result = {**self.result, "events": [{
            **self.result["events"][0], "category": "buying_intent"
        }]}
        with self.assertRaisesRegex(ValueError, "unsupported"):
            discovery_relevance.validate_classification_result(result, self.article)

    def test_irrelevant_company_mention_cannot_carry_events(self):
        result = {
            "relevant": False,
            "event_types": [],
            "company_role": "incidental",
            "business_event": False,
            "physical_implication": False,
            "confidence": 0.88,
            "reason": "The company is mentioned incidentally.",
            "events": [],
        }
        validated = discovery_relevance.validate_classification_result(result, self.article)
        self.assertFalse(validated["relevant"])
        self.assertEqual(validated["events"], [])

    def test_groq_request_leaves_budget_for_json_after_reasoning(self):
        classification = (
            '{"article_index":0,"relevant":false,"event_types":[],"company_role":"incidental",'
            '"business_event":false,"physical_implication":false,"confidence":0.9,'
            '"reason":"No concrete event.","events":[]}'
        )
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=(
                '{"results":[' + classification + ']}'
            )))]
        )
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = completion

        with (
            patch.object(discovery_relevance, "client", fake_client),
            patch.object(discovery_relevance, "wait_for_rate_limit"),
            patch.object(discovery_relevance, "register_request"),
            patch.object(discovery_relevance, "GROQ_MODEL", "openai/gpt-oss-120b"),
        ):
            result = discovery_relevance.classify_articles(
                "Aarti Industries Limited", [self.article]
            )

        self.assertFalse(result[0]["relevant"])
        request = fake_client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["max_tokens"], 3000)
        self.assertEqual(request["reasoning_effort"], "low")


class IngestionTests(unittest.TestCase):
    def setUp(self):
        supabase_module.supabase.reset_mock(return_value=True, side_effect=True)
        self.company = {
            "id": str(uuid4()),
            "name": "Aarti Industries Limited",
            "symbol": "AARTIIND",
            "sector": "Chemicals",
        }
        self.article = {
            "title": "Aarti Industries announces factory expansion",
            "summary": "A new factory expansion is planned.",
            "url": "https://publisher.example/story?id=article-1",
            "normalized_url": "https://publisher.example/story?id=article-1",
            "published_at": "2026-10-01T10:00:00Z",
            "publisher": "Publisher",
            "publisher_url": "https://publisher.example",
            "discovery_source": "google_news_rss",
            "discovery_query": "company plus business-event terms",
            "rss_url": "https://news.google.com/rss/search?q=example",
            "event_types": ["facility_expansion"],
        }
        self.classification = {
            "relevant": True,
            "event_types": ["facility_expansion"],
            "company_role": "subject",
            "business_event": True,
            "physical_implication": True,
            "confidence": 0.9,
            "reason": "The company is the subject of the announcement.",
            "events": [{
                "category": "facility_expansion",
                "description": "The company announced a factory expansion.",
                "supporting_excerpt": "Aarti Industries announces factory expansion",
            }],
        }

    def test_repeated_run_uses_company_article_unique_key_and_stores_provenance(self):
        insert_run = FakeQuery([{"id": "run-1", "status": "processing"}])
        progress_before = FakeQuery([{"id": "run-1", "status": "processing"}])
        prior_query = FakeQuery([])
        progress_classify = FakeQuery([{"id": "run-1", "status": "processing"}])
        article_upsert = FakeQuery([{"id": "article-1"}])
        progress_after = FakeQuery([{"id": "run-1", "status": "processing"}])
        update_run = FakeQuery([{"id": "run-1", "status": "completed"}])
        supabase_module.supabase.table.side_effect = [
            insert_run, progress_before, prior_query, progress_classify,
            article_upsert, progress_after, update_run
        ]

        with (
            patch.object(news_intelligence, "discover_company_news", return_value={
                "articles": [self.article],
                "entry_count": 1,
                "duplicate_count": 2,
                "malformed_count": 0,
                "truncated_count": 0,
                "metadata": {"provider": "google_news_rss", "lookback_days": 30},
            }),
            patch.object(news_intelligence, "classify_articles", return_value=[self.classification]),
        ):
            result = news_intelligence.ingest_company_news(self.company, 30)

        self.assertEqual(result["counts"]["accepted_count"], 1)
        self.assertEqual(result["counts"]["duplicate_count"], 2)
        self.assertEqual(article_upsert.conflict, "company_id,normalized_url")
        self.assertEqual(article_upsert.payload["company_id"], self.company["id"])
        self.assertEqual(article_upsert.payload["events"][0]["source_url"], self.article["url"])
        self.assertEqual(article_upsert.payload["events"][0]["supporting_excerpt"], self.classification["events"][0]["supporting_excerpt"])

    def test_repeated_classified_article_reuses_saved_result_without_groq(self):
        insert_run = FakeQuery([{"id": "run-reuse", "status": "processing"}])
        progress_before = FakeQuery([{"id": "run-reuse", "status": "processing"}])
        prior_query = FakeQuery([{
            "normalized_url": self.article["normalized_url"],
            "events": [{"category": "facility_expansion"}],
            "relevance": self.classification,
            "relevance_status": "accepted",
            "processing_status": "events_extracted",
        }])
        progress_classify = FakeQuery([{"id": "run-reuse", "status": "processing"}])
        update_run = FakeQuery([{
            "id": "run-reuse",
            "status": "completed",
            "metadata": {"progress": {"reused": 1}},
        }])
        supabase_module.supabase.table.side_effect = [
            insert_run, progress_before, prior_query, progress_classify, update_run
        ]

        with (
            patch.object(news_intelligence, "discover_company_news", return_value={
                "articles": [self.article], "duplicate_count": 0,
                "entry_count": 1, "malformed_count": 0,
                "truncated_count": 0, "metadata": {},
            }),
            patch.object(news_intelligence, "classify_articles") as classify,
        ):
            result = news_intelligence.ingest_company_news(self.company, 30)

        classify.assert_not_called()
        self.assertEqual(result["counts"]["accepted_count"], 1)
        self.assertEqual(result["run"]["metadata"]["progress"]["reused"], 1)

    def test_classifier_failure_does_not_overwrite_a_previously_stored_article(self):
        insert_run = FakeQuery([{"id": "run-2", "status": "processing"}])
        progress_before = FakeQuery([{"id": "run-2", "status": "processing"}])
        prior_query = FakeQuery([{
            "normalized_url": self.article["normalized_url"],
            "events": [{"category": "facility_expansion"}],
        }])
        progress_classify = FakeQuery([{"id": "run-2", "status": "processing"}])
        progress_after = FakeQuery([{"id": "run-2", "status": "processing"}])
        update_run = FakeQuery([{"id": "run-2", "status": "failed"}])
        supabase_module.supabase.table.side_effect = [
            insert_run, progress_before, prior_query, progress_classify,
            progress_after, update_run,
        ]

        with (
            patch.object(news_intelligence, "discover_company_news", return_value={
                "articles": [self.article], "duplicate_count": 0,
                "entry_count": 1, "malformed_count": 0,
                "truncated_count": 0, "metadata": {},
            }),
            patch.object(news_intelligence, "classify_articles", return_value=[None]),
        ):
            result = news_intelligence.ingest_company_news(self.company, 30)

        self.assertEqual(result["run"]["status"], "failed")
        self.assertEqual(result["counts"]["failed_count"], 1)
        self.assertEqual(supabase_module.supabase.table.call_count, 6)

    def test_discovery_failure_closes_run_as_failed(self):
        insert_run = FakeQuery([{"id": "run-3", "status": "processing"}])
        progress_before = FakeQuery([{"id": "run-3", "status": "processing"}])
        update_run = FakeQuery([{"id": "run-3", "status": "failed"}])
        supabase_module.supabase.table.side_effect = [insert_run, progress_before, update_run]

        with patch.object(
            news_intelligence,
            "discover_company_news",
            side_effect=discovery.requests.RequestException("provider unavailable"),
        ):
            with self.assertRaises(news_intelligence.NewsProviderFailure):
                news_intelligence.ingest_company_news(self.company, 30)

        self.assertEqual(update_run.payload["status"], "failed")
        self.assertEqual(update_run.payload["failure_reason"], "provider unavailable")

    def test_rejected_article_is_persisted_without_events(self):
        insert_run = FakeQuery([{"id": "run-4", "status": "processing"}])
        progress_before = FakeQuery([{"id": "run-4", "status": "processing"}])
        prior_query = FakeQuery([])
        progress_classify = FakeQuery([{"id": "run-4", "status": "processing"}])
        article_upsert = FakeQuery([{"id": "article-2"}])
        progress_after = FakeQuery([{"id": "run-4", "status": "processing"}])
        update_run = FakeQuery([{"id": "run-4", "status": "completed"}])
        supabase_module.supabase.table.side_effect = [
            insert_run, progress_before, prior_query, progress_classify,
            article_upsert, progress_after, update_run
        ]
        rejected = {
            **self.classification,
            "relevant": False,
            "event_types": [],
            "company_role": "incidental",
            "business_event": False,
            "events": [],
        }

        with (
            patch.object(news_intelligence, "discover_company_news", return_value={
                "articles": [self.article], "duplicate_count": 0,
                "entry_count": 1, "malformed_count": 0,
                "truncated_count": 0, "metadata": {},
            }),
            patch.object(news_intelligence, "classify_articles", return_value=[rejected]),
        ):
            result = news_intelligence.ingest_company_news(self.company, 30)

        self.assertEqual(result["counts"]["rejected_count"], 1)
        self.assertEqual(article_upsert.payload["relevance_status"], "rejected")
        self.assertEqual(article_upsert.payload["events"], [])

    def test_article_persistence_failure_is_reported_as_partial_run(self):
        insert_run = FakeQuery([{"id": "run-5", "status": "processing"}])
        progress_before = FakeQuery([{"id": "run-5", "status": "processing"}])
        prior_query = FakeQuery([])
        progress_classify = FakeQuery([{"id": "run-5", "status": "processing"}])
        article_upsert = FakeQuery([])
        progress_after = FakeQuery([{"id": "run-5", "status": "processing"}])
        update_run = FakeQuery([{"id": "run-5", "status": "completed_with_errors"}])
        supabase_module.supabase.table.side_effect = [
            insert_run, progress_before, prior_query, progress_classify,
            article_upsert, progress_after, update_run
        ]

        with (
            patch.object(news_intelligence, "discover_company_news", return_value={
                "articles": [self.article], "duplicate_count": 0,
                "entry_count": 1, "malformed_count": 0,
                "truncated_count": 0, "metadata": {},
            }),
            patch.object(news_intelligence, "classify_articles", return_value=[self.classification]),
        ):
            result = news_intelligence.ingest_company_news(self.company, 30)

        self.assertEqual(result["run"]["status"], "completed_with_errors")
        self.assertEqual(result["counts"]["persistence_failed_count"], 1)
        self.assertEqual(update_run.payload["failure_reason"], "1 persistence failures")


class NewsApiTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()
        self.company = {"id": str(uuid4()), "name": "Example Industries"}

    def test_unknown_company_is_404(self):
        with patch.object(company_routes, "_get_company_by_identifier", return_value=None):
            response = self.client.get("/api/company-intelligence/no-such-company/news")
        self.assertEqual(response.status_code, 404)

    def test_invalid_lookback_is_rejected(self):
        with patch.object(company_routes, "_get_company_by_identifier", return_value=self.company):
            response = self.client.post(
                f"/api/company-intelligence/{self.company['id']}/news/ingest?days=120"
            )
        self.assertEqual(response.status_code, 400)

    def test_news_retrieval_contract(self):
        result = {"state": "not_fetched", "articles": [], "latest_run": None}
        with (
            patch.object(company_routes, "_get_company_by_identifier", return_value=self.company),
            patch.object(company_routes, "get_company_news", return_value=result),
        ):
            response = self.client.get(
                f"/api/company-intelligence/{self.company['id']}/news"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["state"], "not_fetched")
        self.assertEqual(response.json["articles"], [])

    def test_ingestion_is_queued_for_background_processing(self):
        run = {"id": "run-1", "status": "processing"}
        with (
            patch.object(company_routes, "_get_company_by_identifier", return_value=self.company),
            patch.object(company_routes, "queue_company_news_ingestion", return_value=run) as enqueue,
        ):
            response = self.client.post(
                f"/api/company-intelligence/{self.company['id']}/news/ingest?days=7"
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json["status"], "processing")
        self.assertEqual(response.json["run"]["id"], "run-1")
        enqueue.assert_called_once_with(self.company, lookback_days=7)

    def test_production_origin_is_allowed_when_environment_omits_it(self):
        with patch.dict(os.environ, {"CORS_ORIGINS": "https://other.example"}):
            client = create_app().test_client()

        response = client.options(
            f"/api/reports/companies/{self.company['id']}/ingest",
            headers={
                "Origin": "https://worksphere-lead-generation.vercel.app",
                "Access-Control-Request-Method": "POST",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "https://worksphere-lead-generation.vercel.app",
        )

    def test_news_errors_include_cors_headers(self):
        with (
            patch.object(company_routes, "_get_company_by_identifier", return_value=self.company),
            patch.object(
                company_routes,
                "get_company_news",
                side_effect=news_intelligence.NewsPersistenceFailure(
                    "Stored company news is unavailable."
                ),
            ),
        ):
            response = self.client.get(
                f"/api/company-intelligence/{self.company['id']}/news",
                headers={"Origin": "https://worksphere-lead-generation.vercel.app"},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "https://worksphere-lead-generation.vercel.app",
        )

    def test_report_ingestion_errors_include_cors_headers(self):
        company_query = MagicMock()
        company_query.select.return_value = company_query
        company_query.eq.return_value = company_query
        company_query.maybe_single.return_value = company_query
        company_query.execute.return_value.data = {
            **self.company,
            "symbol": "EXAMPLE",
        }

        with (
            patch.object(report_routes.supabase, "table", return_value=company_query),
            patch.object(
                report_routes,
                "queue_company_report_ingestion",
                side_effect=RuntimeError("upstream unavailable"),
            ),
        ):
            response = self.client.post(
                f"/api/reports/companies/{self.company['id']}/ingest",
                headers={"Origin": "https://worksphere-lead-generation.vercel.app"},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "https://worksphere-lead-generation.vercel.app",
        )

    def test_report_ingestion_is_queued_without_blocking_request(self):
        company_query = MagicMock()
        company_query.select.return_value = company_query
        company_query.eq.return_value = company_query
        company_query.maybe_single.return_value = company_query
        company_query.execute.return_value.data = {
            **self.company,
            "symbol": "EXAMPLE",
        }
        job = {"id": str(uuid4()), "status": "processing"}

        with (
            patch.object(report_routes.supabase, "table", return_value=company_query),
            patch.object(
                report_routes,
                "queue_company_report_ingestion",
                return_value=job,
            ) as queue,
        ):
            response = self.client.post(
                f"/api/reports/companies/{self.company['id']}/ingest"
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json["job_id"], job["id"])
        queue.assert_called_once_with({
            **self.company,
            "symbol": "EXAMPLE",
        })

    def test_report_ingestion_status_is_company_scoped(self):
        job_id = str(uuid4())
        job = {
            "id": job_id,
            "company_id": self.company["id"],
            "status": "completed",
            "result": {"id": str(uuid4())},
        }

        with patch.object(
            report_routes,
            "get_company_report_ingestion",
            return_value=job,
        ) as get_job:
            response = self.client.get(
                f"/api/reports/companies/{self.company['id']}/ingest-runs/{job_id}"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["job"], job)
        get_job.assert_called_once_with(self.company["id"], job_id)

    def test_report_processing_returns_accepted_and_joins_existing_run(self):
        report_id = str(uuid4())
        with patch.object(
            report_routes,
            "queue_report_processing",
            return_value={"status": "processing", "report_id": report_id},
        ) as queue:
            response = self.client.post(
                f"/api/reports/{report_id}/process",
                headers={"Origin": "https://worksphere-lead-generation.vercel.app"},
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json["status"], "processing")
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "https://worksphere-lead-generation.vercel.app",
        )
        queue.assert_called_once_with(report_id)

    def test_report_processing_status_returns_persisted_run_state(self):
        report_id = str(uuid4())
        status = {
            "report_id": report_id,
            "status": "processing",
            "latest_run": {"id": str(uuid4()), "status": "running"},
        }
        with patch.object(
            report_routes,
            "get_report_processing_status",
            return_value=status,
        ) as get_status:
            response = self.client.get(
                f"/api/reports/{report_id}/status"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "processing")
        self.assertEqual(response.json["latest_run"]["status"], "running")
        get_status.assert_called_once_with(report_id)

    def test_duplicate_report_ingestion_joins_existing_job(self):
        company = {**self.company, "symbol": "EXAMPLE"}
        insert_query = MagicMock()
        insert_query.insert.return_value.select.return_value.execute.side_effect = (
            RuntimeError(
                "duplicate key violates unique constraint "
                "ux_report_ingestion_runs_one_processing_per_company"
            )
        )
        active_job = {"id": str(uuid4()), "status": "processing"}
        lookup_query = MagicMock()
        lookup_query.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
            active_job
        ]
        with patch.object(
            report_ingestion_jobs.supabase,
            "table",
            side_effect=[insert_query, lookup_query],
        ):
            result = report_ingestion_jobs.queue_company_report_ingestion(company)

        self.assertEqual(result, active_job)

    def test_processing_request_joins_non_stale_active_run(self):
        report_id = str(uuid4())
        with (
            patch.object(
                report_processing_jobs,
                "get_annual_report",
                return_value={
                    "id": report_id,
                    "processing_status": "processing",
                },
            ),
            patch.object(report_processing_jobs, "_latest_run", return_value={
                "id": str(uuid4()),
                "status": "running",
                "started_at": "2099-01-01T00:00:00+00:00",
            }),
            patch.object(
                report_processing_jobs,
                "_REPORT_PROCESSING_EXECUTOR",
            ) as executor,
        ):
            result = report_processing_jobs.queue_report_processing(report_id)

        self.assertEqual(result, {"status": "processing", "report_id": report_id})
        executor.submit.assert_not_called()

    def test_stale_processing_lock_is_released_and_run_is_failed(self):
        report_id = str(uuid4())
        run_id = str(uuid4())
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        query = MagicMock()
        query.update.return_value.eq.return_value.eq.return_value.lt.return_value.select.return_value.execute.return_value.data = [
            {"id": report_id}
        ]
        with (
            patch.object(
                report_processing_jobs.supabase,
                "table",
                return_value=query,
            ),
            patch.object(
                report_processing_jobs,
                "fail_processing_run",
            ) as fail_run,
        ):
            recovered = report_processing_jobs._recover_stale_processing(
                {
                    "id": report_id,
                    "processing_status": "processing",
                    "updated_at": stale_time,
                },
                {
                    "id": run_id,
                    "status": "running",
                    "started_at": stale_time,
                },
            )

        self.assertTrue(recovered)
        query.update.assert_called_once_with({"processing_status": "failed"})
        fail_run.assert_called_once_with(
            run_id,
            "Processing stopped without completing. Retry the report.",
        )
