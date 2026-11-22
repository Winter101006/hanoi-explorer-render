"""Offline indexing script for Hanoi places.

Reads project/bot/data/hanoi_places_cleaned.json, validates schemas,
computes paraphrase-multilingual-MiniLM-L12-v2 dense embeddings,
and stores them into persistent ChromaDB.
"""
import argparse
import logging
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project.bot.src.chatbot.config import BOT_DIR, load_settings
from project.bot.src.chatbot.chroma_manager import ChromaManager, compute_dataset_fingerprint
from project.bot.src.web.services.chat_service import runtime_settings
from project.bot.src.chatbot.data_loader import load
from project.bot.src.chatbot.embedding import EmbeddingManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("index_data")


def main():
    parser = argparse.ArgumentParser(description="Index Hanoi places into ChromaDB.")
    parser.add_argument("--force", action="store_true", help="Force rebuild even if indexed")
    parser.add_argument("--batch-size", type=int, default=64, help="Embedding batch size")
    args = parser.parse_args()

    settings = load_settings()
    logger.info(f"Target dataset: {settings.data_path}")
    logger.info(f"Chroma DB path: {settings.chroma_path}")
    logger.info(f"Embedding model: {settings.embedding_model} on {settings.device}")

    # Load and validate dataset
    t0 = time.time()
    places = load(settings.data_path)
    logger.info(f"Loaded {len(places)} validated places in {time.time() - t0:.2f}s")

    chroma_mgr = ChromaManager(runtime_settings(settings))

    if not args.force and chroma_mgr.is_indexed(expected_count=len(places)):
        metadata = chroma_mgr.get_collection_metadata()
        expected = {'dataset_fingerprint': compute_dataset_fingerprint(places), 'model': settings.embedding_model,
                    'document_version': settings.document_version, 'dimension': 384, 'normalized': True,
                    'hnsw:space': 'cosine'}
        if any(metadata.get(key) != value for key, value in expected.items()):
            parser.error('Index metadata differs. Set CHROMA_COLLECTION to a new name and rerun.')
        logger.info(f"Collection '{settings.collection}' is already up-to-date with {len(places)} items. Use --force to rebuild.")
        return 0

    embedder = EmbeddingManager(model_name=settings.embedding_model, device=settings.device)

    t1 = time.time()
    indexed_count = chroma_mgr.index_places(places, embedding_manager=embedder, batch_size=args.batch_size)
    logger.info(f"Indexing completed: {indexed_count} places in {time.time() - t1:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
