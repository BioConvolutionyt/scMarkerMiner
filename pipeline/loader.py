"""
pipeline/loader.py — 数据入库模块

读取 data/extracted/ 下经过基因标准化的 JSON 文件，
通过 CRUD 操作写入 MySQL 数据库。每篇文献作为一个事务提交。
"""

import json
import logging
from pathlib import Path

from tqdm import tqdm

from config.settings import EXTRACTED_DIR, ensure_dirs
from database.models import SessionLocal, init_db
from database.crud import get_or_create_paper, insert_cell_marker_entry

logger = logging.getLogger(__name__)


class DatabaseLoader:
    """将 LLM 抽取 + 基因标准化后的结果批量写入 MySQL。"""

    def __init__(self):
        ensure_dirs()
        init_db()
        logger.info("Database tables initialized")

    def load_file(self, json_path: Path) -> int:
        """
        加载单个 extracted JSON 文件到数据库。

        返回本次新插入的 entry 条数。
        """
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Cannot read %s: %s", json_path.name, exc)
            return 0

        pmcid = data.get("pmcid")
        markers = data.get("markers", [])
        if not pmcid or not markers:
            return 0

        db = SessionLocal()
        inserted = 0

        try:
            paper = get_or_create_paper(
                db,
                pmcid=pmcid,
                pmid=data.get("pmid"),
                title=data.get("title"),
                journal=None,
                pub_year=None,
            )

            for m in markers:
                cell_type = m.get("cell_type")
                marker_symbol = m.get("marker")
                if not cell_type or not marker_symbol:
                    continue

                entry = insert_cell_marker_entry(
                    db,
                    paper_id=paper.id,
                    cell_type_name=cell_type,
                    marker_symbol=marker_symbol,
                    cell_subtype_name=m.get("cell_subtype"),
                    tissue_name=m.get("tissue"),
                    disease_name=m.get("disease"),
                    marker_status=m.get("marker_status", "approved"),
                )
                if entry is not None:
                    inserted += 1

            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to load %s — rolled back", json_path.name)
        finally:
            db.close()

        return inserted

    def load_all(self) -> int:
        """
        批量加载 data/extracted/ 下全部 JSON 到数据库。

        返回新插入的 entry 总数。
        """
        json_files = sorted(EXTRACTED_DIR.glob("PMC*.json"))
        if not json_files:
            logger.warning("No extracted files in %s", EXTRACTED_DIR)
            return 0

        logger.info("Loading %d extracted files into database", len(json_files))

        total_inserted = 0
        files_loaded = 0

        for fp in tqdm(json_files, desc="DB loading", unit="file"):
            n = self.load_file(fp)
            total_inserted += n
            if n > 0:
                files_loaded += 1

        db = SessionLocal()
        try:
            from database.models import Paper, Marker, CellType, CellMarkerEntry
            n_papers = db.query(Paper).count()
            n_markers = db.query(Marker).count()
            n_cell_types = db.query(CellType).count()
            n_entries = db.query(CellMarkerEntry).count()
        finally:
            db.close()

        logger.info("=" * 50)
        logger.info("Database loading summary")
        logger.info("  Files processed   : %d", len(json_files))
        logger.info("  Files with inserts: %d", files_loaded)
        logger.info("  New entries added  : %d", total_inserted)
        logger.info("  --- Totals in DB ---")
        logger.info("  Papers      : %d", n_papers)
        logger.info("  Markers     : %d", n_markers)
        logger.info("  Cell types  : %d", n_cell_types)
        logger.info("  Entries     : %d", n_entries)
        logger.info("=" * 50)

        return total_inserted


# =====================================================================
# 直接运行入口
# =====================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    loader = DatabaseLoader()
    loader.load_all()
