"""BAAI/bge-small-en-v1.5 on ONNX Runtime: the memory embedder.

The same model the memory system was calibrated on (every retrieval threshold
in tuning.py assumes its score range), run without torch. bge-small's
sentence-transformers config is CLS pooling followed by L2 normalisation
(1_Pooling/config.json: pooling_mode_cls_token), which is exactly what
__call__ does, so the vectors match the old sentence-transformers ones to
float tolerance.

Why not sentence-transformers: it pulled in torch, which was 0.5 GB on
Windows/macOS and 2.6 GB of CUDA libraries on Linux, needed the Visual C++
runtime to import, and has no Intel-Mac wheels at all. onnxruntime and
tokenizers were already dependencies (chromadb's own).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import numpy as np
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from chromadb.utils.embedding_functions import register_embedding_function

MODEL_ID = "BAAI/bge-small-en-v1.5"
MAX_TOKENS = 512
BATCH_SIZE = 32


def _model_dir() -> Path:
    from app import embedding_model

    return embedding_model.ensure()


@register_embedding_function
class OnnxBgeSmallEmbeddingFunction(EmbeddingFunction[Documents]):
    """ChromaDB embedding function backed by the provisioned ONNX model."""

    def __init__(self) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        directory = _model_dir()
        self._tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=MAX_TOKENS)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        options = ort.SessionOptions()
        options.log_severity_level = 3  # errors only
        self._session = ort.InferenceSession(
            str(directory / "model.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self._input_names = {i.name for i in self._session.get_inputs()}

    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002 (chroma's name)
        vectors: List[np.ndarray] = []
        for start in range(0, len(input), BATCH_SIZE):
            vectors.extend(self._embed(list(input[start : start + BATCH_SIZE])))
        return vectors

    def _embed(self, texts: List[str]) -> List[np.ndarray]:
        encoded = self._tokenizer.encode_batch(texts)
        feeds = {
            "input_ids": np.array([e.ids for e in encoded], dtype=np.int64),
            "attention_mask": np.array(
                [e.attention_mask for e in encoded], dtype=np.int64
            ),
            "token_type_ids": np.array([e.type_ids for e in encoded], dtype=np.int64),
        }
        feeds = {k: v for k, v in feeds.items() if k in self._input_names}
        hidden = self._session.run(None, feeds)[0]  # (batch, seq, 384)
        cls = hidden[:, 0, :]
        norms = np.linalg.norm(cls, axis=1, keepdims=True)
        cls = cls / np.clip(norms, 1e-12, None)
        return [row.astype(np.float32) for row in cls]

    @staticmethod
    def name() -> str:
        return "craftbot_onnx_bge_small"

    def get_config(self) -> Dict[str, Any]:
        # The model location is resolved at build time, not stored: moving
        # CRAFTBOT_HOME must not strand a collection's config.
        return {"model": MODEL_ID}

    @staticmethod
    def build_from_config(config: Dict[str, Any]) -> "OnnxBgeSmallEmbeddingFunction":
        return OnnxBgeSmallEmbeddingFunction()

    def default_space(self) -> str:
        return "cosine"

    def supported_spaces(self) -> List[str]:
        return ["cosine", "l2", "ip"]

    def is_legacy(self) -> bool:
        return False
