"""Query-time retrieval: embed -> vector search -> optional rerank."""
from . import config
from .embed import Embedder
from .store import Store


class Searcher:
    def __init__(self, store: Store, embedder: Embedder, reranker=None):
        self.store = store
        self.embedder = embedder
        self.reranker = reranker

    def search(self, query, k=None, *, source_type=None, author=None, arm=None, per_source=None) -> list[dict]:
        """The k nearest passages, at most `per_source` from one source (None: the configured
        default; 0: no limit), so a list of k names several sources and not one paper k times.
        get_neighbors gives the passages around a hit."""
        k = k or config.default_k()
        cap = config.max_per_source() if per_source is None else per_source
        fetch = max(k, 40) if self.reranker else k
        if cap:
            fetch = max(fetch, 5 * k)
        vec = self.embedder.embed_query(query)
        hits = self.store.search(vec, fetch, source_type=source_type, author=author, arm=arm)
        if self.reranker and hits:
            scores = self.reranker.predict([(query, h["text"]) for h in hits])
            for h, s in zip(hits, scores):
                h["score"] = float(s)
            hits.sort(key=lambda h: h["score"], reverse=True)
        if cap:
            seen: dict[str, int] = {}
            kept = []
            for h in hits:
                seen[h["source_id"]] = seen.get(h["source_id"], 0) + 1
                if seen[h["source_id"]] <= cap:
                    kept.append(h)
            hits = kept
        return hits[:k]

    def get_neighbors(self, source_id, ordinal, radius=1) -> list[dict]:
        lo = max(0, ordinal - radius)
        return self.store.neighbors(source_id, range(lo, ordinal + radius + 1))


def build_default() -> "Searcher":
    """Wire a Searcher from config (used by the MCP server)."""
    store = Store(config.INDEX_DIR)
    embedder = Embedder()
    reranker = None
    name = config.reranker_model()
    if name:
        from sentence_transformers import CrossEncoder
        reranker = CrossEncoder(name, device=embedder.device)
    return Searcher(store, embedder, reranker=reranker)
