"""Embedding generator supporting lightweight ONNX Runtime (for 512MB Render) and SentenceTransformer fallback.

Outputs L2-normalized 384-dimensional dense vectors for semantic search.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Union

import numpy as np

from project.bot.src.chatbot.config import BOT_DIR, EMBEDDING_MODEL
from project.bot.src.chatbot.schemas import Place, RawPlace

logger = logging.getLogger(__name__)

_global_model = None
_global_onnx = None

ONNX_DIR = BOT_DIR / 'onnx_model'
ONNX_MODEL_PATH = ONNX_DIR / 'model_quint8_avx2.onnx'
SP_MODEL_PATH = ONNX_DIR / 'sentencepiece.bpe.model'


class _OnnxMiniLMEmbedder:
    """Low-RAM ONNX Runtime + SentencePiece embedder (~230MB total process RSS)."""

    def __init__(self, onnx_path: Path, sp_path: Path):
        import onnxruntime as ort
        import sentencepiece as spm

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        opts.enable_mem_pattern = False
        opts.enable_cpu_mem_arena = False
        self.session = ort.InferenceSession(str(onnx_path), opts, providers=['CPUExecutionProvider'])
        self.input_names = {inp.name for inp in self.session.get_inputs()}
        self.sp = spm.SentencePieceProcessor(model_file=str(sp_path))

    def _tokenize(self, text: str, max_len: int = 128) -> List[int]:
        raw_ids = self.sp.encode(text, out_type=int)
        # Map SentencePiece IDs to XLM-RoBERTa vocab IDs: 0(unk)->3, 1(bos)->0, 2(eos)->2, >=3->id+1
        mapped = [
            3 if tid == 0 else (0 if tid == 1 else (2 if tid == 2 else tid + 1))
            for tid in raw_ids[: max_len - 2]
        ]
        return [0] + mapped + [2]

    def encode(self, texts: List[str], normalize_embeddings: bool = True, show_progress_bar: bool = False):
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)

        token_lists = [self._tokenize(t) for t in texts]
        max_len = max(len(ids) for ids in token_lists)
        batch_size = len(token_lists)

        input_ids = np.ones((batch_size, max_len), dtype=np.int64)  # <pad> = 1
        attention_mask = np.zeros((batch_size, max_len), dtype=np.int64)
        for i, ids in enumerate(token_lists):
            input_ids[i, : len(ids)] = ids
            attention_mask[i, : len(ids)] = 1

        feeds = {'input_ids': input_ids, 'attention_mask': attention_mask}
        if 'token_type_ids' in self.input_names:
            feeds['token_type_ids'] = np.zeros_like(input_ids)

        token_embeddings = self.session.run(None, feeds)[0].astype(np.float32)
        mask_expanded = attention_mask[..., None].astype(np.float32)
        summed = (token_embeddings * mask_expanded).sum(axis=1)
        counts = np.clip(mask_expanded.sum(axis=1), 1e-9, None)
        pooled = summed / counts

        if normalize_embeddings:
            norms = np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
            pooled = pooled / norms
        return pooled


def get_model(model_name: str = EMBEDDING_MODEL, device: str = 'cpu'):
    """Lazy load lightweight ONNX embedder if packaged, else SentenceTransformer."""
    global _global_model, _global_onnx
    if ONNX_MODEL_PATH.is_file() and SP_MODEL_PATH.is_file():
        if _global_onnx is None:
            logger.info('Loading lightweight ONNX MiniLM embedder from %s', ONNX_DIR)
            _global_onnx = _OnnxMiniLMEmbedder(ONNX_MODEL_PATH, SP_MODEL_PATH)
        return _global_onnx

    if _global_model is None:
        from sentence_transformers import SentenceTransformer
        logger.info('Loading embedding model: %s on %s', model_name, device)
        try:
            _global_model = SentenceTransformer(model_name, device=device, local_files_only=True)
        except Exception:
            _global_model = SentenceTransformer(model_name, device=device)
    return _global_model


def build_document_text(place: Union[Place, RawPlace]) -> str:
    """Format rich text representation of a place for document indexing."""
    raw = place.source if isinstance(place, Place) else place
    parts = [
        f"Địa điểm: {raw.name}",
        f"Thể loại: {raw.category}",
        f"Khu vực: {raw.district}",
        f"Địa chỉ: {raw.address}",
    ]
    if raw.description:
        parts.append(f"Mô tả: {raw.description}")
    if raw.suitable_for:
        parts.append(f"Phù hợp: {raw.suitable_for}")
    if raw.weather_fit:
        parts.append(f"Thời tiết: {raw.weather_fit}")
    if raw.tags:
        parts.append(f"Đặc điểm: {', '.join(raw.tags)}")
    if raw.price_range:
        parts.append(f"Khoảng giá: {raw.price_range}")
    return ". ".join(parts)


def encode(texts: List[str], model_name: str = EMBEDDING_MODEL, device: str = 'cpu') -> List[List[float]]:
    """Encode texts into normalized 384-d vectors per contract."""
    if not texts:
        return []
    model = get_model(model_name=model_name, device=device)
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [vec.tolist() for vec in embeddings]


class EmbeddingManager:
    """Class wrapper for embedding operations with injectable model/device."""

    def __init__(self, model_name: str = EMBEDDING_MODEL, device: str = 'cpu'):
        self.model_name = model_name
        self.device = device
        self._model = None

    @property
    def model(self):
        if self._model is None:
            self._model = get_model(self.model_name, self.device)
        return self._model

    def encode(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        embeddings = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [vec.tolist() for vec in embeddings]

    def encode_query(self, query: str) -> List[float]:
        results = self.encode([query])
        return results[0] if results else [0.0] * 384
