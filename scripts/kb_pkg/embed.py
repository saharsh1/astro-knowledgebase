"""Local sentence-embedding wrapper.

Device is governed by config.KB_DEVICE (default "cpu"). Pass device="auto" to
let sentence-transformers pick the GPU when one is available — index.py does
this for builds, while the MCP server stays on CPU so it can't wedge on a busy
CUDA context.
"""
from . import config

_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def _resolve_device(device: str | None) -> str | None:
    """Map a config value to a sentence-transformers device argument.

    "auto" (or empty) => None, letting the library auto-detect (GPU if present).
    Anything else ("cpu", "cuda", "cuda:1", ...) is passed through unchanged.
    """
    device = device if device is not None else config.device()
    if not device or device == "auto":
        return None
    return device


class Embedder:
    def __init__(self, model_name: str | None = None, encoder=None, device: str | None = None):
        self.model_name = model_name or config.embedding_model()
        self.device = _resolve_device(device)
        self._encoder = encoder  # injected for tests

    @property
    def encoder(self):
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer
            self._encoder = SentenceTransformer(self.model_name, device=self.device,
                                                revision=config.model_revision())
        return self._encoder

    @property
    def dim(self) -> int:
        return self.encoder.get_sentence_embedding_dimension()

    def token_counter(self):
        """A function words -> token counts with the model's own tokenizer, or None.

        BERT-style tokenizers split on whitespace before WordPiece, so counting each
        whitespace-separated word on its own gives the exact count of the joined text
        (plus the two special tokens the encoder adds).
        """
        tok = getattr(self.encoder, "tokenizer", None)
        if tok is None:
            return None

        def count(words: list[str]) -> list[int]:
            if not words:
                return []
            ids = tok(words, add_special_tokens=False)["input_ids"]
            return [len(x) for x in ids]

        return count

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        arr = self.encoder.encode(texts, normalize_embeddings=True)
        return [list(map(float, row)) for row in arr]

    def embed_query(self, query: str) -> list[float]:
        text = query
        if "bge" in self.model_name.lower():
            text = _BGE_QUERY_PREFIX + query
        arr = self.encoder.encode([text], normalize_embeddings=True)
        return list(map(float, arr[0]))
