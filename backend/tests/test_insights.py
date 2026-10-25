"""
Search insights: the ranked-file overview, per-file topics, search sessions, the dashboard
and topics endpoints, and the summary job (per-file summaries, caching, rate limits,
fallbacks, token budgets, cancellation), with the LLM replaced by a fake.
"""
import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from tests.test_search_engine import _search, api_library, fake_models, indexed  # noqa: F401  (fixtures)


# ── helpers ──────────────────────────────────────────────────────────────────
def _rows(lib, names=None):
    """Light session rows for the indexed files, best first (as the engine overview builds them)."""
    out = []
    for i, r in enumerate(lib.db.all("SELECT * FROM sources WHERE kind = 'document' ORDER BY name")):
        if names and r["name"] not in names:
            continue
        out.append({
            "id": f"src-{r['id']}", "sourceId": r["id"], "libraryId": lib.id, "libraryName": lib.name,
            "category": r["kind"], "title": r["name"], "fileType": r["ext"], "fileSize": r["size"],
            "relPath": r["rel_path"], "folder": r["folder"] or "", "relevanceScore": round(0.9 - i * 0.01, 4),
            "snippet": "", "modifiedAt": None, "takenAt": None, "indexedAt": None,
        })
    return out


class FakeLLM:
    """Stands in for get_async_groq_client(): answers per-file JSON and overall markdown prompts."""

    def __init__(self, fail=None, rate_limit_first=0, answer=None):
        self.calls = []
        self.answer = answer          # fixed text for every answer, instead of the JSON below
        self.fail = fail
        self.rate_limit_first = rate_limit_first
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kw):
        self.calls.append(kw)
        if self.fail is not None:
            raise self.fail
        if len(self.calls) <= self.rate_limit_first:
            raise RuntimeError("429 Too Many Requests: rate limit reached")
        if self.answer is not None:
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.answer))],
                                   usage=None)
        system = kw["messages"][0]["content"]
        if "files for a search" in system:
            content = json.dumps({"summary": "A short summary of the file.", "topics": ["Monsoon Planning"],
                                  "events": ["Planning Meeting"]})
        else:
            content = "<think>hidden</think>" + json.dumps({"overview": "Overall: the files cover planning [1][2]."})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                               usage=SimpleNamespace(prompt_tokens=120, completion_tokens=40))


@pytest.fixture
def llm(monkeypatch):
    def install(**kw):
        fake = FakeLLM(**kw)
        monkeypatch.setattr("app.search.summary.get_async_groq_client", lambda: fake)
        return fake
    import app.search.summary as summary
    monkeypatch.setattr(summary, "MAX_WAIT", 0.0)      # retries do not really wait
    return install


def _job(session_id="s", user="u"):
    from app.search.session import SummaryJob
    return SummaryJob("j", session_id, user, "k")


# ── overview and result dates ────────────────────────────────────────────────
def test_overview_has_a_row_for_every_ranked_file(indexed):
    res = _search("monsoon planning rainfall meeting recipes mango")
    shown = {i["id"] for i in res.all()}
    overview = {r["id"]: r for r in res.overview}
    assert shown <= set(overview)
    row = overview[next(iter(shown))]
    assert {"sourceId", "libraryId", "category", "fileType", "folder", "relevanceScore", "modifiedAt"} <= set(row)
    assert row["modifiedAt"] and row["modifiedAt"].startswith("20")
    assert all("modifiedAt" in i for i in res.all())


# ── topics ───────────────────────────────────────────────────────────────────
def test_topics_are_derived_once_and_follow_the_file(indexed):
    from app.search.insights import get_insights
    lib = indexed
    sid = lib.db.scalar("SELECT id FROM sources WHERE name = 'notes.txt'")
    first = get_insights(lib, sid)
    assert first["origin"] == "index" and first["topics"]
    assert lib.db.scalar("SELECT COUNT(*) FROM source_insights WHERE source_id = ?", (sid,)) == 1

    lib.db.execute("UPDATE source_insights SET topics_json = ? WHERE source_id = ?", (json.dumps(["Marker"]), sid))
    assert get_insights(lib, sid)["topics"] == ["Marker"]          # cached, not derived again

    lib.db.execute("UPDATE sources SET fingerprint = 'changed' WHERE id = ?", (sid,))
    assert get_insights(lib, sid)["topics"] != ["Marker"]          # the file changed: derived again


def test_llm_topics_win_until_the_file_changes(indexed):
    from app.search.insights import cached_llm_summary, get_insights, save_llm_insights
    lib = indexed
    sid = lib.db.scalar("SELECT id FROM sources WHERE name = 'notes.txt'")
    save_llm_insights(lib, sid, "About the monsoon meeting.", ["Monsoon Planning"], ["Planning Meeting"], "m")
    got = get_insights(lib, sid)
    assert got["origin"] == "llm" and got["topics"] == ["Monsoon Planning"] and got["summary"]
    assert cached_llm_summary(lib, sid)["summary"] == "About the monsoon meeting."
    lib.db.execute("UPDATE sources SET fingerprint = 'changed' WHERE id = ?", (sid,))
    assert cached_llm_summary(lib, sid) is None
    assert get_insights(lib, sid)["origin"] == "index"


# ── sessions ─────────────────────────────────────────────────────────────────
def test_sessions_belong_to_their_user_and_the_cut_is_relative():
    from app.search.session import create_session, cut_rows, get_session
    rows = [{"relevanceScore": s} for s in (0.9, 0.88, 0.7, 0.3, 0.1)]
    sid = create_session("1", "q", rows)
    assert get_session(sid, "1") is not None
    assert get_session(sid, "2") is None
    assert get_session("nope", "1") is None
    assert [r["relevanceScore"] for r in cut_rows(rows, 0.05, 0.2)] == [0.9, 0.88]
    assert [r["relevanceScore"] for r in cut_rows(rows, 0.30, 0.2)] == [0.9, 0.88, 0.7]   # 0.6 and up
    assert [r["relevanceScore"] for r in cut_rows(rows, 1.0, 0.2)] == [0.9, 0.88, 0.7, 0.3]   # floor 0.2


# ── API: search id, dashboard, topics ────────────────────────────────────────
def test_smart_search_returns_a_search_id_and_the_dashboard_uses_it(api_library, admin_client):
    c = admin_client
    body = c.post("/api/search/smart", json={"query": "drainage contract"}).json()
    assert body["searchId"] and body["local"]["documents"][0]["title"] == "minutes.txt"

    everything = c.post("/api/search/dashboard", json={"searchId": body["searchId"], "relativeThreshold": 100})
    assert everything.status_code == 200, everything.text
    data = everything.json()
    assert data["totals"]["kept"] == len(data["files"]) >= 1
    first = data["files"][0]
    assert first["title"] == "minutes.txt" and first["topics"] and first["modifiedAt"]

    best_only = c.post("/api/search/dashboard", json={"searchId": body["searchId"], "relativeThreshold": 0}).json()
    assert [f["title"] for f in best_only["files"]] == ["minutes.txt"]
    assert best_only["totals"]["candidates"] == data["totals"]["candidates"]

    assert c.post("/api/search/dashboard", json={"searchId": "gone"}).status_code == 404


def test_topics_endpoint_only_serves_files_of_the_search(api_library, admin_client):
    c = admin_client
    body = c.post("/api/search/smart", json={"query": "drainage contract"}).json()
    doc = body["local"]["documents"][0]
    asked = [{"libraryId": doc["libraryId"], "sourceId": doc["sourceId"]},
             {"libraryId": doc["libraryId"], "sourceId": "not-in-this-search"}]
    topics = c.post("/api/search/topics", json={"searchId": body["searchId"], "ids": asked}).json()["topics"]
    assert list(topics) == [doc["sourceId"]] and topics[doc["sourceId"]]["topics"]


# ── summary job ──────────────────────────────────────────────────────────────
async def test_each_file_is_summarised_then_all_together(indexed, llm):
    from app.search.insights import get_insights
    from app.search.summary import run_summary_job
    fake = llm()
    rows = _rows(indexed, {"notes.txt", "recipes.txt", "report.pdf"})
    job = _job()
    await run_summary_job(job, rows, "monsoon")
    assert job.status == "done" and job.done == job.total == len(rows) >= 2
    assert all(d["state"] == "done" and d["source"] == "llm" and d["summary"] for d in job.docs)
    assert job.overall.startswith("Overall") and "hidden" not in job.overall       # <think> stripped
    assert job.usage["calls"] == len(rows) + 1 == len(fake.calls)
    assert job.usage["promptTokens"] == 120 * job.usage["calls"]
    # what the LLM said is stored as the file's topics
    sid = rows[0]["sourceId"]
    assert get_insights(indexed, sid)["origin"] == "llm"


async def test_a_second_search_reuses_stored_summaries(indexed, llm):
    from app.search.summary import run_summary_job
    fake = llm()
    rows = _rows(indexed, {"notes.txt", "recipes.txt"})
    await run_summary_job(_job(), rows, "monsoon")
    before = len(fake.calls)
    again = _job()
    await run_summary_job(again, rows, "something else")
    assert again.usage["cachedDocs"] == len(rows) and all(d["source"] == "cache" for d in again.docs)
    assert len(fake.calls) - before == 1                                       # only the overall summary


async def test_rate_limits_are_retried(indexed, llm):
    from app.search.summary import run_summary_job
    fake = llm(rate_limit_first=2)
    job = _job()
    await run_summary_job(job, _rows(indexed, {"notes.txt"}), "monsoon")
    assert job.status == "done" and job.docs[0]["source"] == "llm"
    assert len(fake.calls) == 3 and job.usage["calls"] == 1                    # failed attempts are not counted


async def test_files_fall_back_to_their_text_when_the_llm_fails(indexed, llm):
    from app.search.summary import run_summary_job
    llm(fail=ValueError("No GROQ_API_KEY configured in environment."))
    job = _job()
    await run_summary_job(job, _rows(indexed, {"notes.txt", "recipes.txt"}), "monsoon")
    assert job.status == "done" and job.error is None
    assert all(d["source"] == "extractive" and d["summary"] for d in job.docs)
    assert job.overall is None and job.warnings and job.usage["calls"] == 0


async def test_one_file_alone_needs_no_overall_call(indexed, llm):
    from app.search.summary import run_summary_job
    fake = llm()
    job = _job()
    await run_summary_job(job, _rows(indexed, {"notes.txt"}), "monsoon")
    assert len(fake.calls) == 1 and job.overall == job.docs[0]["summary"]


async def test_prompts_stay_inside_the_token_budget(indexed, llm, monkeypatch):
    from app.core.config import settings
    from app.ai.groq_client import estimate_tokens
    from app.search.summary import run_summary_job
    monkeypatch.setattr(settings, "SUMMARY_DOC_INPUT_TOKENS", 60)
    fake = llm()
    await run_summary_job(_job(), _rows(indexed, {"notes.txt", "recipes.txt", "report.pdf"}), "monsoon")
    for kw in fake.calls:
        assert kw["max_tokens"] <= 850                                         # the router's Groq cap
    doc_calls = [kw for kw in fake.calls if "JSON" in kw["messages"][0]["content"]]
    assert doc_calls and all(estimate_tokens(kw["messages"][1]["content"]) < 60 + 250 for kw in doc_calls)


async def test_summaries_too_big_for_one_call_are_combined_in_groups(indexed, llm, monkeypatch):
    from app.core.config import settings
    from app.search.summary import run_summary_job
    monkeypatch.setattr(settings, "SUMMARY_OVERALL_INPUT_TOKENS", 20)         # one summary per group
    fake = llm()
    rows = _rows(indexed, {"notes.txt", "recipes.txt", "report.pdf"})
    job = _job()
    await run_summary_job(job, rows, "monsoon")
    assert len(fake.calls) == len(rows) + len(rows) + 1                        # files + groups + final
    assert job.overall


async def test_a_cancelled_job_stops_before_calling_the_llm(indexed, llm):
    from app.search.summary import run_summary_job
    fake = llm()
    job = _job()
    job.cancelled = True
    await run_summary_job(job, _rows(indexed, {"notes.txt", "recipes.txt"}), "monsoon")
    assert job.status == "cancelled" and not fake.calls


# ── API: the summary job over HTTP ───────────────────────────────────────────
def test_summary_endpoints_start_poll_and_isolate_jobs(api_library, admin_client, llm):
    fake = llm()
    c = admin_client
    body = c.post("/api/search/smart", json={"query": "drainage contract"}).json()
    started = c.post("/api/search/summary", json={"searchId": body["searchId"]})
    assert started.status_code == 200, started.text
    job_id = started.json()["jobId"]
    # the same request joins the same job instead of starting another
    assert c.post("/api/search/summary", json={"searchId": body["searchId"]}).json()["jobId"] == job_id

    deadline = time.time() + 20
    view = {}
    while time.time() < deadline:
        view = c.get(f"/api/search/summary/{job_id}").json()
        if view["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert view["status"] == "done", view
    assert view["docs"][0]["title"] == "minutes.txt" and view["docs"][0]["summary"]
    assert view["progress"] == {"done": len(view["docs"]), "total": len(view["docs"])}
    assert fake.calls

    assert c.get("/api/search/summary/unknown").status_code == 404
    assert c.delete(f"/api/search/summary/{job_id}").status_code == 200


async def test_reasoning_around_the_json_is_ignored(indexed, llm):
    from app.search.summary import extract_json, run_summary_job
    answer = ('Thinking Process:\n1. **Analyze** the file {not json}.\n\n'
              '{"summary": "The meeting moved to Friday.", "topics": ["Monsoon"], "events": []}')
    assert extract_json(answer, "summary")["summary"] == "The meeting moved to Friday."
    assert extract_json('```json\n[{"overview": "x"}]\n```', "overview") == {"overview": "x"}
    assert extract_json("no json at all", "summary") == {}
    llm(answer=answer)
    job = _job()
    await run_summary_job(job, _rows(indexed, {"notes.txt"}), "monsoon")
    assert job.docs[0]["source"] == "llm" and job.docs[0]["summary"] == "The meeting moved to Friday."
    assert job.usage["promptTokens"] > 0 and job.usage["completionTokens"] > 0       # estimated: no usage in the answer


@pytest.mark.parametrize("answer", [
    "Thinking Process:\n1. **Analyze the Request**: the user wants a summary...",
    '{"summary": "...", "topics": [], "events": []}',
    '{"summary": "<what the file is and says>"}',
])
async def test_an_answer_without_a_real_summary_is_never_shown(indexed, llm, answer):
    from app.search.summary import run_summary_job
    llm(answer=answer)
    job = _job()
    await run_summary_job(job, _rows(indexed, {"notes.txt"}), "monsoon")
    doc = job.docs[0]
    assert doc["source"] == "extractive" and "Thinking" not in doc["summary"] and "monsoon" in doc["summary"].lower()
