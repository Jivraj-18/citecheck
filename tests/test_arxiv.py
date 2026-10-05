from citecheck import arxiv


def test_title_query_is_a_quoted_phrase_without_punctuation():
    q = arxiv.title_query('FastTree: Optimizing "Attention" Kernel & {Runtime} for LLM-Inference.')
    assert q == 'ti:"FastTree Optimizing Attention Kernel Runtime for LLM Inference"'


def test_title_query_handles_latex_and_accents():
    assert arxiv.title_query(r"Learning \emph{Fast} Na\"ive Models") == 'ti:"Learning Fast Naive Models"'


def test_title_query_keeps_the_word_and_inside_the_exact_phrase():
    assert arxiv.title_query("Learning and Planning") == 'ti:"Learning and Planning"'


class FakeResponse:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}


def test_get_backs_off_longer_and_honors_retry_after(monkeypatch):
    responses = [FakeResponse(429, {"Retry-After": "90"}), FakeResponse(429), FakeResponse(503), FakeResponse(200)]
    sleeps = []
    monkeypatch.setattr(arxiv.httpx, "get", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(arxiv.time, "sleep", sleeps.append)
    monkeypatch.setattr(arxiv, "_last_request", 0.0)
    assert arxiv._get("https://export.arxiv.org/api/query").status_code == 200
    backoffs = [s for s in sleeps if s >= 30]
    assert backoffs == [90, 120, 240]  # Retry-After first, then doubling from 60 s
