import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import FakeProvider, fake_embedder

from seshat.config import load_config, write_default_config
from seshat.inference.journal import generate_entry
from seshat.papers.ingest import chunk_text, extract_pdf, ingest_pdf
from seshat.papers.linking import link_session_papers, papers_near_session
from seshat.store.db import Store
from seshat.store.vectors import VectorStore
from seshat.watcher.daemon import WatchService

T0 = datetime(2026, 7, 1, 10, 0, 0, tzinfo=UTC)

SMOTE_TEXT = (
    "SMOTE: Synthetic Minority Over-sampling Technique.\n\n"
    "We propose an over-sampling approach in which the minority class is "
    "over-sampled by creating synthetic examples rather than by over-sampling "
    "with replacement. Oversampling improves minority class F1 on imbalanced data.\n"
)


def ts(days: float) -> str:
    return (T0 + timedelta(days=days)).isoformat(timespec="seconds")


def make_pdf(path: Path, text: str = SMOTE_TEXT) -> Path:
    import pymupdf

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page()
    # insert_textbox wraps long lines; insert_text would clip at the page edge.
    page.insert_textbox(pymupdf.Rect(72, 72, 520, 770), text, fontsize=11)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def env(tmp_path: Path):
    store = Store.open(tmp_path)
    vectors = VectorStore(tmp_path, embedder=fake_embedder)
    yield tmp_path, store, vectors
    store.close()


# -- extraction and chunking ----------------------------------------------------


def test_extract_pdf_title_and_text(env):
    root, _, _ = env
    pdf = make_pdf(root / "papers" / "smote.pdf")
    title, text = extract_pdf(pdf)
    assert title.startswith("SMOTE")
    assert "synthetic examples" in text


def test_chunking_respects_size_and_overlap():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(20))
    chunks = chunk_text(text, size=500, overlap=100)
    assert len(chunks) > 3
    assert all(len(c) <= 500 for c in chunks)
    assert chunks[0][-40:].split()[0] in chunks[1][:200]  # overlap carries text over


def test_chunking_empty_text():
    assert chunk_text("   \n  ") == []


# -- ingestion --------------------------------------------------------------------


def test_ingest_creates_paper_and_chunks(env):
    root, store, vectors = env
    pdf = make_pdf(root / "papers" / "smote.pdf")
    paper_id = ingest_pdf(store, vectors, pdf, "papers/smote.pdf", added_at=ts(0))

    paper = store.paper_by_path("papers/smote.pdf")
    assert paper.id == paper_id
    assert paper.title.startswith("SMOTE")
    assert paper.added_at == ts(0)
    assert vectors.count("papers") >= 1
    hits = vectors.query("papers", "minority class oversampling")
    assert hits[0].metadata["paper_id"] == paper_id


def test_ingest_is_idempotent_by_path(env):
    root, store, vectors = env
    pdf = make_pdf(root / "papers" / "smote.pdf")
    assert ingest_pdf(store, vectors, pdf, "papers/smote.pdf") is not None
    assert ingest_pdf(store, vectors, pdf, "papers/smote.pdf") is None
    assert len(store.papers()) == 1


# -- time-proximity linking -------------------------------------------------------


def session_at(store: Store, start_days: float, end_days: float) -> int:
    session_id = store.create_session(started_at=ts(start_days))
    store.close_session(session_id, ended_at=ts(end_days))
    return session_id


def test_papers_near_session_window(env):
    _, store, _ = env
    store.add_paper("papers/recent.pdf", title="recent", added_at=ts(8))
    store.add_paper("papers/old.pdf", title="old", added_at=ts(-5))
    store.add_paper("papers/later.pdf", title="later", added_at=ts(20))
    session_id = session_at(store, 10, 10.1)  # window: day 3 .. day 10.1

    nearby = papers_near_session(store, store.get_session(session_id))
    assert [p.title for p in nearby] == ["recent"]


def test_link_session_papers_idempotent(env):
    _, store, _ = env
    paper_id = store.add_paper("papers/x.pdf", title="x", added_at=ts(0))
    session_id = session_at(store, 1, 1.5)
    paper = store.paper_by_path("papers/x.pdf")
    assert link_session_papers(store, session_id, [paper]) == 1
    assert link_session_papers(store, session_id, [paper]) == 0
    edges = store.edges(src=("session", session_id), kind="time-proximity")
    assert len(edges) == 1
    assert edges[0].dst_id == paper_id
    assert edges[0].confidence == 0.3


# -- the exit criterion: paper -> code change -> entry references it -------------


def smote_session(store: Store) -> int:
    session_id = store.create_session(started_at=ts(2))
    event_id = store.append_event(
        "notebook_diff",
        {
            "added": [{"id": "c1", "index": 0,
                       "source": "sm = SMOTE()\nX_res, y_res = sm.fit_resample(X, y)",
                       "outputs": ["minority F1: 0.68"], "execution_count": 3}],
            "removed": [], "modified": [], "reordered": False,
            "kernel_restarted": False, "cell_count": 2,
        },
        path="train.ipynb",
        ts=ts(2),
    )
    store.assign_events_to_session([event_id], session_id)
    store.close_session(session_id, ended_at=ts(2.1))
    return session_id


def test_paper_context_reaches_prompt_and_edge_is_recorded(env):
    root, store, vectors = env
    pdf = make_pdf(root / "papers" / "smote.pdf")
    ingest_pdf(store, vectors, pdf, "papers/smote.pdf", added_at=ts(0))
    session_id = smote_session(store)

    provider = FakeProvider()
    entry = generate_entry(store, vectors, provider, session_id)

    prompt = provider.prompts[0]
    assert "Papers the researcher read recently" in prompt
    assert "SMOTE" in prompt  # the relevant chunk was pulled in
    assert entry is not None

    edges = store.edges(src=("session", session_id), kind="time-proximity")
    assert len(edges) == 1
    assert edges[0].dst_id == store.paper_by_path("papers/smote.pdf").id


def test_no_papers_means_no_papers_section(env):
    _, store, vectors = env
    session_id = smote_session(store)
    provider = FakeProvider()
    generate_entry(store, vectors, provider, session_id)
    assert "Papers the researcher read recently" not in provider.prompts[0]


def test_reprocess_does_not_duplicate_paper_edges(env):
    root, store, vectors = env
    pdf = make_pdf(root / "papers" / "smote.pdf")
    ingest_pdf(store, vectors, pdf, "papers/smote.pdf", added_at=ts(0))
    session_id = smote_session(store)

    generate_entry(store, vectors, FakeProvider(), session_id)
    generate_entry(
        store, vectors,
        FakeProvider(json.dumps({"what_changed": "reprocessed"})),
        session_id,
    )
    assert len(store.edges(src=("session", session_id), kind="time-proximity")) == 1


# -- watcher integration ----------------------------------------------------------


def test_watcher_ingests_dropped_pdf(env):
    root, store, vectors = env
    write_default_config(root)
    service = WatchService(root, load_config(root), store, vectors=vectors)

    pdf = make_pdf(root / "papers" / "smote.pdf")
    assert service.process_file(pdf) is None  # no raw event, papers aren't session work
    assert store.paper_by_path("papers/smote.pdf") is not None
    assert store.events() == []  # and no session was opened


def test_baseline_scan_ingests_preexisting_pdfs(env):
    root, store, vectors = env
    write_default_config(root)
    make_pdf(root / "papers" / "smote.pdf")
    service = WatchService(root, load_config(root), store, vectors=vectors)
    service.baseline_scan()
    assert store.paper_by_path("papers/smote.pdf") is not None


def test_watcher_without_vectors_skips_papers_gracefully(env):
    root, store, _ = env
    write_default_config(root)
    logs = []
    service = WatchService(root, load_config(root), store, log=logs.append)
    pdf = make_pdf(root / "papers" / "smote.pdf")
    assert service.process_file(pdf) is None
    assert store.paper_by_path("papers/smote.pdf") is None
    assert any("no vector store" in line for line in logs)
