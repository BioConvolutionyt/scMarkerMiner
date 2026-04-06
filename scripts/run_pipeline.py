"""
scripts/run_pipeline.py — 数据流水线统一运行入口

根据 config/settings.py 中的 PILOT_MODE 开关，自动决定处理规模。
PILOT_MODE = True  → 仅处理 100 篇（快速验证）
PILOT_MODE = False → 全量处理
"""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import PILOT_MODE, PILOT_SIZE, BATCH_LIMIT
from pipeline.fetcher import NCBIFetcher
from pipeline.parser import PMCParser
from pipeline.extractor import MarkerExtractor
from pipeline.validator import GeneValidator
from pipeline.normalizer import DataNormalizer
from pipeline.loader import DatabaseLoader


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
        ],
    )


def main():
    setup_logging()
    logger = logging.getLogger("run_pipeline")

    mode = f"PILOT ({PILOT_SIZE} papers)" if PILOT_MODE else "FULL"
    batch_info = f" | Batch limit: {BATCH_LIMIT}" if BATCH_LIMIT > 0 else ""
    logger.info("Pipeline mode: %s%s", mode, batch_info)

    # --- Stage 1: Data Fetching ---
    logger.info(">>> Stage 1: Fetching articles from NCBI PMC")
    fetcher = NCBIFetcher()
    n_fetched = fetcher.run()
    logger.info("Stage 1 done — %d new articles downloaded\n", n_fetched)

    # --- Stage 2: Text Preprocessing ---
    logger.info(">>> Stage 2: Parsing XML & extracting text")
    parser = PMCParser()
    n_parsed = parser.process_all(limit=BATCH_LIMIT)
    logger.info("Stage 2 done — %d new articles parsed\n", n_parsed)

    # --- Stage 3: LLM Extraction ---
    logger.info(">>> Stage 3: LLM marker extraction (GPT-4o-mini)")
    extractor = MarkerExtractor()
    n_extracted = extractor.process_all(limit=BATCH_LIMIT)
    logger.info("Stage 3 done — %d papers extracted\n", n_extracted)

    # --- Stage 4: Gene Symbol Validation ---
    logger.info(">>> Stage 4: HGNC gene symbol standardization")
    validator = GeneValidator()
    n_validated = validator.process_all()
    logger.info("Stage 4 done — %d files validated\n", n_validated)

    # --- Stage 5: Data Normalization ---
    logger.info(">>> Stage 5: Cell type / tissue / disease normalization")
    normalizer = DataNormalizer()
    n_normalized = normalizer.process_all()
    logger.info("Stage 5 done — %d files normalized\n", n_normalized)

    # --- Stage 5b: Type-Subtype Deduplication ---
    logger.info(">>> Stage 5b: Resolving cell_type == cell_subtype duplicates")
    n_dedup = normalizer.resolve_type_subtype_duplicates()
    logger.info("Stage 5b done — %d entries fixed\n", n_dedup)

    # --- Stage 6: Database Loading ---
    logger.info(">>> Stage 6: Loading data into MySQL")
    loader = DatabaseLoader()
    n_loaded = loader.load_all()
    logger.info("Stage 6 done — %d new entries loaded\n", n_loaded)

    logger.info("Pipeline finished.")


if __name__ == "__main__":
    main()
