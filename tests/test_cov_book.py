"""Book ingestion branches (issue #26): real wikisvc, git wiki and extraction worker.

Only the model is scripted, and every answer is checked against the grammar the agent
sent. Crashes are the ones a process really has: the service handled a request and the
answer never came back, so the next run must recover from what the wiki already holds.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from test_agent_failures import (
    EMPTY_REVIEW,
    NEW,
    QUOTES,
    Book,
    agent,
    book,
    candidate,
    chapter,
    draft_rules,
    review_ids,
)
from test_library_extract import extract, library

from wikiagent.jobs.ingest_book import IngestBook
from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError

# The fake's callback protocol hands the model's input data over as dict[str, Any].
Data = dict[str, Any]
Observe = Callable[[httpx.Request], None]
ACTOR = {"name": "alice", "person": "alice", "clearance": "restricted"}


def lost_response(
    client: TestClient, matches: Callable[[httpx.Request], bool], lost: list[str]
) -> Observe:
    """The service handles the first matching request; the process dies before the answer."""

    def observe(request: httpx.Request) -> None:
        if lost or not matches(request):
            return
        handled = client.request(
            request.method, str(request.url), headers=dict(request.headers), content=request.content
        )
        assert handled.status_code == 200, handled.text
        lost.append(request.method + " " + request.url.path.removeprefix("/api/v1"))
        raise RuntimeError("Process stopped after the service answered")

    return observe


def job_row(job: Book) -> Data:
    [row] = job.agent.state.rows("SELECT * FROM jobs WHERE id=?", (job.job,))
    return {**row, "progress": json.loads(row["progress"])}


def feedback(job: Book, n: int) -> list[str]:
    """Correction messages sent with each book_chapter request for chapter ``n``."""
    return [
        request["messages"][-1]["content"]
        for request, (task, data) in zip(job.agent.fake.requests, job.agent.fake.calls, strict=True)
        if task == "book_chapter" and data["chapter"]["n"] == n and len(request["messages"]) > 2
    ]


# A plain-text book: the service cuts text files into 4000-character pages and finds
# chapters by their headings, so chapter 1 spans pages 1-2 and chapter 2 is page 3.
PAGE_QUOTE = "Keep field names stable across releases"
FILLER = " Operators read these events during incidents and audits."


def padded(text: str) -> str:
    while len(text) < 4000:
        text += FILLER
    return text[:4000]


TEXT_BOOK = (
    padded("Chapter 1\n\nUse structured logs for every operation.")
    + padded("Logs are records for machines first." + FILLER * 15 + " " + PAGE_QUOTE + ".")
    + "Chapter 2\n\nUse asynchronous HTTP clients in async handlers."
)


def text_book(
    client: TestClient,
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    respond: Callable[[str, Data], Data],
    *,
    extracted: bool = True,
    data: bytes = TEXT_BOOK.encode(),
    name: str = "handbook.txt",
) -> Book:
    ag = agent(client, tmp_path, monkeypatch, respond)
    client.headers["Authorization"] = "Bearer " + ag.token
    raw = library(client, name, data)
    if extracted:
        extract(client, raw["path"])
    payload = {"raw_path": raw["path"], "title": "Handbook"}
    job = ag.state.job("ingest_book", ACTOR, payload)
    return Book(IngestBook(ag.wiki, ag.models, ag.state), job, payload, ag)


def page_candidate(thesis: str, quote: str, page: int) -> dict[str, object]:
    return candidate(
        1, thesis=thesis, quote=quote, locator={"unit": "стр.", "start": page, "end": None}
    )


def test_long_chapter_is_read_in_chunks_and_page_quotes_are_checked_on_their_pages(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = "Use structured logs for every operation."
    second = "Keep log field names stable across releases."

    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            if data["chapter"]["n"] == 2:
                return chapter()
            if PAGE_QUOTE in data["text"]:
                return chapter(page_candidate(second, PAGE_QUOTE, 2))
            return chapter(page_candidate(first, first, 1))
        if task == "classify":
            return NEW
        assert task == "book_review", task
        return EMPTY_REVIEW

    job = text_book(client, config, tmp_path, monkeypatch, respond)
    # 1700 tokens: 4250 characters per request, so the 8000-character chapter takes two.
    job.agent.settings.limits.chapter_chunk_tokens = 1700
    whole = client.get(
        f"/api/v1/raw/{job.payload['raw_path']}/text", params={"chapter": 1, "max_chars": 60000}
    ).json()["text"]
    assert 4250 < len(whole) <= 8500
    assert PAGE_QUOTE not in whole[:4250] and PAGE_QUOTE in whole[4250:]
    job.run()
    reads = [
        (d["pages"], d["text"])
        for t, d in job.agent.fake.calls
        if t == "book_chapter" and d["chapter"]["n"] == 1
    ]
    assert reads == [("1-2", whole[:4250]), ("1-2", whole[4250:])]
    rules = job.rules()
    assert set(rules) == {first, second}
    # The quote lives on page 2: only the excerpt around the cited page could confirm it.
    assert f'стр. 2 "{PAGE_QUOTE}"]' in rules[second]["body_md"]
    assert f'стр. 1 "{first}"]' in rules[first]["body_md"]
    assert job.agent.state.restore(job.job, "report")["errors"] == []
    pid = job.pid()
    assert job.agent.wiki.request("GET", f"/proposals/{pid}/validate")["errors"] == []
    assert job.agent.wiki.request("GET", "/proposals/" + pid)["status"] == "submitted"


def test_quote_over_thirty_words_is_sent_back_to_the_model(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    long_quote = " ".join([QUOTES[0]] * 6)  # 36 words, all of them from the chapter
    attempts: list[int] = []

    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            n = data["chapter"]["n"]
            if n == 1:
                attempts.append(n)
                if len(attempts) == 1:
                    return chapter(candidate(1, quote=long_quote))
            return chapter(candidate(n))
        if task == "classify":
            return NEW
        assert task == "book_review", task
        return EMPTY_REVIEW

    job = book(client, config, tmp_path, monkeypatch, respond)
    job.run()
    assert len(attempts) == 2
    [correction] = feedback(job, 1)
    assert "E_QUOTE_TOO_LONG: не более 30 слов" in correction
    rules = job.rules()
    assert set(rules) == set(QUOTES)
    assert f'гл. 1 "{QUOTES[0]}"]' in rules[QUOTES[0]]["body_md"]
    assert job.agent.state.restore(job.job, "report")["errors"] == []


def test_carried_book_state_is_trimmed_to_the_token_budget(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    long_summary = "Сводка прочитанного: " + "логи, запросы, типы. " * 20
    references = [f"Глава {n}: подробности про журналирование событий" for n in range(4, 9)]

    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            n = data["chapter"]["n"]
            result = chapter(candidate(n))
            if n == 1:
                return {**result, "state_summary": long_summary, "open_references": references}
            return {**result, "state_summary": "Идеи книги.", "open_references": references}
        if task == "classify":
            return NEW
        assert task == "book_review", task
        return EMPTY_REVIEW

    job = book(client, config, tmp_path, monkeypatch, respond)
    # The smallest budget the config allows: 100 tokens, 250 characters of JSON.
    job.agent.settings.limits.state_tokens = 100
    job.run()
    states = [d["state"] for t, d in job.agent.fake.calls if t == "book_chapter"]
    assert states[0] == {}
    titles = ["Правило главы 1", "Правило главы 2"]
    # Too long even without references and titles: the summary itself is cut.
    assert states[1] == {"summary": long_summary[:50], "titles": [], "open_references": []}
    # Short enough once a few references go: the newest are dropped, the rest stays.
    kept = states[2]["open_references"]
    assert states[2]["summary"] == "Идеи книги." and states[2]["titles"] == titles
    assert 0 < len(kept) < len(references) and kept == references[: len(kept)]
    assert len(json.dumps(states[2], ensure_ascii=False)) <= 250
    one_more = {**states[2], "open_references": references[: len(kept) + 1]}
    assert len(json.dumps(one_more, ensure_ascii=False)) > 250
    assert job.agent.state.restore(job.job, "report")["candidates"] == 3


def test_book_proposal_created_before_a_crash_is_found_by_its_job_marker(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lost: list[str] = []

    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            return chapter(candidate(data["chapter"]["n"]))
        if task == "classify":
            return NEW
        assert task == "book_review", task
        return EMPTY_REVIEW

    created = lost_response(
        client, lambda r: r.method == "POST" and r.url.path == "/api/v1/proposals", lost
    )
    job = book(client, config, tmp_path, monkeypatch, respond, created)
    # Another book's draft by the same agent token must not be taken over.
    other = client.post(
        "/api/v1/proposals",
        json={"kind": "book", "title": "Книга: Другая", "description": "Job another-book"},
    )
    assert other.status_code == 200, other.text
    with pytest.raises(RuntimeError):
        job.run()
    assert lost == ["POST /proposals"] and job.agent.state.restore(job.job, "proposal") is None
    job.run()
    books = {p["pid"]: p for p in job.agent.wiki.all("/proposals", kind="book")}
    assert set(books) == {other.json()["pid"], job.pid()} and job.pid() != other.json()["pid"]
    assert "Job " + job.job in books[job.pid()]["description"]
    assert books[other.json()["pid"]]["status"] == "draft"
    assert job.agent.sent.count("POST /proposals") == 1
    assert set(job.rules()) == set(QUOTES)
    assert job.agent.wiki.request("GET", "/proposals/" + job.pid())["status"] == "submitted"


def test_rule_written_before_a_crash_keeps_its_id_without_an_allocation_record(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lost: list[str] = []

    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            return chapter(candidate(data["chapter"]["n"]))
        if task == "classify":
            return NEW
        assert task == "book_review", task
        return EMPTY_REVIEW

    def chapter_two_written(request: httpx.Request) -> bool:
        return request.method == "PUT" and QUOTES[1].encode() in request.content

    job = book(
        client,
        config,
        tmp_path,
        monkeypatch,
        respond,
        lost_response(client, chapter_two_written, lost),
    )
    with pytest.raises(RuntimeError):
        job.run()
    before = {thesis: page["id"] for thesis, page in job.rules().items()}
    assert set(before) == {QUOTES[0], QUOTES[1]}
    # A job checkpointed by a version before readable IDs has no candidate_ids record;
    # the draft itself is the only memory of the IDs it already used.
    with job.agent.state.connect() as db:
        db.execute("DELETE FROM job_state WHERE job_id=? AND key='candidate_ids'", (job.job,))
    job.run()
    rules = job.rules()
    assert set(rules) == set(QUOTES)
    assert {thesis: rules[thesis]["id"] for thesis in before} == before
    # No second copy of the chapter 2 rule under a suffixed ID.
    assert sorted(draft_rules(job.agent.wiki, job.pid())) == sorted(
        [*before.values(), rules[QUOTES[2]]["id"]]
    )
    assert job.agent.wiki.request("GET", "/proposals/" + job.pid())["status"] == "submitted"


def test_book_waits_for_extraction_it_started_itself(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            return chapter()
        if task == "classify":
            return NEW
        assert task == "book_review", task
        return EMPTY_REVIEW

    job = text_book(client, config, tmp_path, monkeypatch, respond, extracted=False)
    job.run()
    extract_calls = job.agent.sent.count(f"POST /raw/{job.payload['raw_path']}/extract")
    assert extract_calls >= 2
    assert [d["chapter"]["n"] for t, d in job.agent.fake.calls if t == "book_chapter"] == [1, 2]
    assert job.agent.wiki.request("GET", "/proposals/" + job.pid())["status"] == "submitted"


def test_book_retries_extraction_once_at_start_and_never_while_polling(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            return chapter()
        if task == "classify":
            return NEW
        assert task == "book_review", task
        return EMPTY_REVIEW

    job = text_book(client, config, tmp_path, monkeypatch, respond, extracted=False)
    wiki = job.agent.wiki
    original = wiki.request
    extracts: list[dict[str, str] | None] = []

    def spy(method: str, path: str, **kwargs: Any) -> Any:
        if method == "POST" and path.endswith("/extract"):
            extracts.append(kwargs.get("params"))
        return original(method, path, **kwargs)

    monkeypatch.setattr(wiki, "request", spy)
    job.run()
    assert len(extracts) >= 2
    assert extracts[0] == {"retry": "true"}
    assert extracts[1:] == [None] * (len(extracts) - 1)


def test_book_stops_waiting_for_extraction_at_the_deadline(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(task: str, data: Data) -> Data:
        raise AssertionError("The model is called only after the book is extracted: " + task)

    job = text_book(client, config, tmp_path, monkeypatch, respond, extracted=False)
    readings: list[float] = []

    def clock() -> float:
        # The deadline is set from the first reading; every later one is a day past it.
        readings.append(0.0 if not readings else 86400.0 * len(readings))
        return readings[-1]

    ingest = IngestBook(job.agent.wiki, job.agent.models, job.agent.state, clock=clock)
    with pytest.raises(WikiError) as error:
        ingest.run(job.job, job.payload)
    assert (error.value.code, error.value.message) == (
        "E_EXTRACT_TIMEOUT",
        "Ожидание извлечения превысило лимит.",
    )
    assert readings == [0.0, 86400.0]
    assert job.agent.sent == [f"POST /raw/{job.payload['raw_path']}/extract"]
    assert job.agent.fake.calls == [] and job.agent.wiki.all("/proposals", kind="book") == []


def test_book_with_failed_extraction_fails_with_the_extraction_error(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = text_book(
        client,
        config,
        tmp_path,
        monkeypatch,
        lambda task, data: EMPTY_REVIEW,
        extracted=False,
        data=b" \n\n \n",
        name="blank.txt",
    )
    with pytest.raises(WikiError) as error:
        job.run()
    assert error.value.code == "E_NO_TEXT_LAYER"
    status = client.get(f"/api/v1/raw/{job.payload['raw_path']}/outline")
    assert status.status_code == 409
    assert not [
        s for s in job.agent.sent if s.startswith(("PUT", "PATCH")) or s == "POST /proposals"
    ]
    assert job.agent.fake.calls == []


def test_book_resumed_after_a_lost_submit_reports_instead_of_writing_again(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lost: list[str] = []

    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            return chapter(candidate(data["chapter"]["n"]))
        if task == "classify":
            return NEW
        assert task == "book_review", task
        return EMPTY_REVIEW

    def submit(request: httpx.Request) -> bool:
        return request.method == "POST" and request.url.path.endswith("/submit")

    job = book(client, config, tmp_path, monkeypatch, respond, lost_response(client, submit, lost))
    with pytest.raises(RuntimeError):
        job.run()
    pid = job.pid()
    assert lost == [f"POST /proposals/{pid}/submit"]
    assert job.agent.state.restore(job.job, "report") is None
    calls, sent = len(job.agent.fake.calls), len(job.agent.sent)
    job.run()
    expected = {"proposal": pid, "candidates": 3, "chapters_done": 3}
    row = job_row(job)
    assert (row["status"], row["progress"]) == ("awaiting_review", expected)
    assert len(job.agent.fake.calls) == calls
    assert not [s for s in job.agent.sent[sent:] if not s.startswith(("GET", "POST /raw/"))]
    human = {"Authorization": "Bearer " + job.agent.human}
    accepted = client.post(
        f"/api/v1/proposals/{pid}/accept", headers=human, json={"promote": [], "deprecate": []}
    )
    assert accepted.status_code == 200, accepted.text
    job.run()
    row = job_row(job)
    assert (row["status"], row["progress"]) == ("done", expected)
    assert len(job.agent.fake.calls) == calls


def test_classified_relation_to_a_new_target_is_added_to_the_rule(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    targets: list[str] = []

    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            return chapter(candidate(data["chapter"]["n"]))
        if task == "classify":
            if data["claim"]["text"] != QUOTES[0]:
                return NEW
            page = next(p for p in data["pages"] if p["type"] == "rule")
            targets.append(page["id"])
            relation = {
                "relation": "refines",
                "target": page["id"],
                "confidence": 0.9,
                "quote": page["summary"],
                "reason": "Уточняет существующее правило.",
            }
            return {"relations": [relation]}
        assert task == "book_review", task
        return EMPTY_REVIEW

    job = book(client, config, tmp_path, monkeypatch, respond)
    job.run()
    [target] = targets
    rules = job.rules()
    # The chapter's own candidate named no relation: this one comes from classification.
    assert rules[QUOTES[0]]["relations"] == {"refines": [target]}
    assert rules[QUOTES[1]]["relations"] == {} and rules[QUOTES[2]]["relations"] == {}
    pid = job.pid()
    assert job.agent.wiki.request("GET", f"/proposals/{pid}/validate")["errors"] == []


def test_rule_the_wiki_refuses_is_reported_and_the_book_goes_on(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = 'client = Client(key="AKIAIOSFODNN7EXAMPLE")'

    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            n = data["chapter"]["n"]
            return chapter(candidate(n, **({"good_example": secret} if n == 2 else {})))
        if task == "classify":
            return NEW
        assert task == "book_review", task
        return EMPTY_REVIEW

    job = book(client, config, tmp_path, monkeypatch, respond)
    job.run()
    report = job.agent.state.restore(job.job, "report")
    assert report["errors"] == [{"chapter": 2, "code": "E_SECRET_DETECTED", "thesis": QUOTES[1]}]
    assert report["candidates"] == 2 and set(job.rules()) == {QUOTES[0], QUOTES[2]}
    assert job.agent.wiki.request("GET", "/proposals/" + job.pid())["status"] == "submitted"


def test_link_to_a_merged_duplicate_of_itself_is_not_written(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            return chapter(candidate(data["chapter"]["n"]))
        if task == "classify":
            return NEW
        assert task == "book_review", task
        keep, drop, _ = review_ids(data)
        # After the merge the link would point from the survivor to itself.
        return {
            **EMPTY_REVIEW,
            "merge": [{"keep": keep, "drop": drop}],
            "links": [{"src": keep, "target": drop, "rel": "refines"}],
        }

    job = book(client, config, tmp_path, monkeypatch, respond)
    job.run()
    rules = job.rules()
    assert set(rules) == {QUOTES[0], QUOTES[2]}
    assert rules[QUOTES[0]]["relations"] == {}
    patched = [s for s in job.agent.sent if s.startswith("PATCH")]
    keep = rules[QUOTES[0]]["id"]
    # Only the evidence of the merged duplicate is appended to the survivor.
    assert patched == [f"PATCH /proposals/{job.pid()}/pages/{keep}"]
    assert job.agent.wiki.request("GET", "/proposals/" + job.pid())["status"] == "submitted"


def test_merge_resumed_after_the_duplicate_was_already_deleted(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lost: list[str] = []

    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            return chapter(candidate(data["chapter"]["n"]))
        if task == "classify":
            return NEW
        assert task == "book_review", task
        keep, drop, _ = review_ids(data)
        return {**EMPTY_REVIEW, "merge": [{"keep": keep, "drop": drop}]}

    deleted = lost_response(client, lambda r: r.method == "DELETE", lost)
    job = book(client, config, tmp_path, monkeypatch, respond, deleted)
    with pytest.raises(RuntimeError):
        job.run()
    assert len(lost) == 1 and lost[0].startswith("DELETE ")
    job.run()
    rules = job.rules()
    assert set(rules) == {QUOTES[0], QUOTES[2]}
    assert rules[QUOTES[0]]["body_md"].count("Объединён кандидат ") == 1
    assert [s for s in job.agent.sent if s.startswith("DELETE")] == lost
    assert job.agent.state.restore(job.job, "report")["candidates"] == 2
    assert job.agent.wiki.request("GET", "/proposals/" + job.pid())["status"] == "submitted"


def test_merge_in_a_later_review_batch_redirects_links_made_by_an_earlier_one(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The second pass reviews 40 candidates at a time; 41 make a second batch.
    reads: list[int] = []
    first_batch: list[str] = []
    audits = FILLER.strip().rstrip(".")

    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            if data["chapter"]["n"] == 2:
                thesis = "Book practice number 40 keeps operations observable."
                quote = "Use asynchronous HTTP clients in async handlers."
                return chapter(page_candidate(thesis, quote, 3))
            reads.append(len(reads))
            return chapter(
                *(
                    page_candidate(
                        f"Book practice number {10 * reads[-1] + k:02d} keeps operations observable.",
                        audits,
                        1,
                    )
                    for k in range(10)
                )
            )
        if task == "classify":
            return NEW
        assert task == "book_review", task
        ids = [c["id"] for c in data["candidates"]]
        if not first_batch:
            first_batch.extend(ids)
            # Links among all of the book's candidates, made before the duplicate is known.
            return {
                **EMPTY_REVIEW,
                "links": [
                    {"src": ids[0], "target": ids[1], "rel": "refines"},
                    {"src": ids[2], "target": ids[1], "rel": "depends_on"},
                    {"src": ids[0], "target": ids[3], "rel": "depends_on"},
                ],
            }
        [last] = ids
        return {**EMPTY_REVIEW, "merge": [{"keep": last, "drop": first_batch[1]}]}

    job = text_book(client, config, tmp_path, monkeypatch, respond)
    # 1000 tokens: 2500 characters per request, four requests for chapter 1.
    job.agent.settings.limits.chapter_chunk_tokens = 1000
    job.run()
    assert len(reads) == 4 and len(first_batch) == 40
    drafted = {p["id"]: p for p in job.rules().values()}
    survivor = next(i for i, p in drafted.items() if "number 40" in p["summary"])
    dropped = first_batch[1]
    assert dropped not in drafted and len(drafted) == 40
    # Only the relation to the duplicate moves; the other one is left as it was.
    assert drafted[first_batch[0]]["relations"] == {
        "refines": [survivor],
        "depends_on": [first_batch[3]],
    }
    assert drafted[first_batch[2]]["relations"] == {"depends_on": [survivor]}
    assert drafted[survivor]["body_md"].count("Объединён кандидат " + dropped) == 1
    assert job.agent.fake.count("book_review") == 2
    pid = job.pid()
    assert job.agent.wiki.request("GET", f"/proposals/{pid}/validate")["errors"] == []
    assert job.agent.wiki.request("GET", "/proposals/" + pid)["status"] == "submitted"
    assert job.agent.state.restore(job.job, "report")["candidates"] == 40
