"""
pipeline/validator.py — HGNC 基因符号标准化模块

流程：下载 HGNC Complete Set → 构建 approved/alias 映射表
     → 逐条标准化 LLM 抽取结果中的 marker 字段
     → 合并标准化后的重复条目 → 记录无法映射的基因
"""

import json
import logging
from collections import defaultdict
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm

from config.settings import (
    HGNC_COMPLETE_SET_URL,
    HGNC_CACHE_FILE,
    EXTRACTED_DIR,
    UNMAPPED_GENES_LOG,
    ensure_dirs,
)

logger = logging.getLogger(__name__)


class GeneValidator:
    """基于 HGNC 官方数据的基因符号标准化器。"""

    def __init__(self):
        self._approved_upper: dict[str, str] = {}
        self._alias_upper: dict[str, list[str]] = defaultdict(list)
        self._unmapped: dict[str, int] = {}
        ensure_dirs()
        self._load_hgnc()

    # =================================================================
    # HGNC 数据加载
    # =================================================================

    def _download_hgnc(self):
        """下载 HGNC Complete Set TSV（约 15 MB），已缓存则跳过。"""
        if HGNC_CACHE_FILE.exists():
            logger.info("HGNC cache exists: %s", HGNC_CACHE_FILE.name)
            return

        logger.info("Downloading HGNC Complete Set …")
        resp = requests.get(HGNC_COMPLETE_SET_URL, timeout=120, stream=True)
        resp.raise_for_status()

        with open(HGNC_CACHE_FILE, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                fh.write(chunk)

        size_mb = HGNC_CACHE_FILE.stat().st_size / (1024 * 1024)
        logger.info("HGNC file saved (%.1f MB)", size_mb)

    def _load_hgnc(self):
        """解析 HGNC TSV，构建 case-insensitive 查找表。"""
        self._download_hgnc()

        df = pd.read_csv(HGNC_CACHE_FILE, sep="\t", low_memory=False)

        if "status" in df.columns:
            df = df[df["status"] == "Approved"]

        for symbol in df["symbol"].dropna():
            symbol = str(symbol).strip()
            if symbol:
                self._approved_upper[symbol.upper()] = symbol

        for _, row in df.iterrows():
            approved = str(row["symbol"]).strip()
            for col in ("alias_symbol", "prev_symbol"):
                raw = row.get(col)
                if pd.isna(raw):
                    continue
                for alias in str(raw).split("|"):
                    alias = alias.strip()
                    if not alias:
                        continue
                    key = alias.upper()
                    if approved not in self._alias_upper[key]:
                        self._alias_upper[key].append(approved)

        logger.info(
            "HGNC loaded — %d approved symbols, %d alias entries",
            len(self._approved_upper),
            len(self._alias_upper),
        )

    # =================================================================
    # 单符号标准化
    # =================================================================

    def standardize(self, symbol: str) -> tuple[str, str]:
        """
        标准化单个基因符号。

        返回:
            (standardized_symbol, status)
            status 取值:
                "approved"  — 已是 HGNC 官方符号
                "corrected" — 从别名/旧名成功映射
                "ambiguous" — 一个别名对应多个官方符号，无法自动决定
                "unknown"   — HGNC 中无此符号
        """
        if not symbol or not symbol.strip():
            return symbol or "", "unknown"

        clean = symbol.strip()
        upper = clean.upper()

        if upper in self._approved_upper:
            return self._approved_upper[upper], "approved"

        candidates = self._alias_upper.get(upper, [])
        if len(candidates) == 1:
            return candidates[0], "corrected"
        if len(candidates) > 1:
            logger.debug(
                "Ambiguous alias '%s' → %s", clean, candidates
            )
            return clean, "ambiguous"

        self._unmapped[clean] = self._unmapped.get(clean, 0) + 1
        return clean, "unknown"

    # =================================================================
    # 批量处理
    # =================================================================

    def process_all(self) -> int:
        """
        对 data/extracted/ 下全部 JSON 执行基因符号标准化。

        修改内容：
          - marker → approved symbol
          - 新增 marker_original（仅当修正时保留原值）
          - 新增 marker_status
          - 标准化后的重复条目自动去重
          - 统计信息写入 gene_validation 字段

        返回处理的文件数。
        """
        json_files = sorted(EXTRACTED_DIR.glob("PMC*.json"))
        if not json_files:
            logger.warning("No extracted files in %s", EXTRACTED_DIR)
            return 0

        logger.info("Validating gene symbols in %d files", len(json_files))

        processed = 0
        stats = {"corrected": 0, "ambiguous": 0, "unknown": 0, "deduped": 0}

        for fp in tqdm(json_files, desc="Gene validation", unit="file"):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.error("Cannot read %s: %s", fp.name, exc)
                continue

            markers = data.get("markers", [])
            if not markers:
                continue

            standardized: list[dict] = []
            seen_keys: set[tuple] = set()

            for m in markers:
                original = m.get("marker", "")
                approved, status = self.standardize(original)

                m["marker"] = approved
                m["marker_original"] = original if status in ("corrected", "ambiguous") else None
                m["marker_status"] = status

                stats[status] = stats.get(status, 0) + 1

                dedup_key = (
                    m.get("cell_type"),
                    m.get("cell_subtype"),
                    m["marker"],
                    m.get("tissue"),
                    m.get("disease"),
                )
                if dedup_key in seen_keys:
                    stats["deduped"] += 1
                    continue
                seen_keys.add(dedup_key)
                standardized.append(m)

            data["markers"] = standardized
            data["valid_marker_count"] = len(standardized)
            data["gene_validation"] = {
                "corrected": sum(1 for m in standardized if m["marker_status"] == "corrected"),
                "ambiguous": sum(1 for m in standardized if m["marker_status"] == "ambiguous"),
                "unknown": sum(1 for m in standardized if m["marker_status"] == "unknown"),
            }

            fp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            processed += 1

        self._save_unmapped_log()

        logger.info("=" * 50)
        logger.info("Gene validation summary")
        logger.info("  Files processed    : %d", processed)
        logger.info("  Symbols corrected  : %d", stats["corrected"])
        logger.info("  Symbols ambiguous  : %d", stats["ambiguous"])
        logger.info("  Symbols unknown    : %d", stats["unknown"])
        logger.info("  Duplicates removed : %d", stats["deduped"])
        logger.info("  Unique unmapped    : %d", len(self._unmapped))
        logger.info("=" * 50)
        return processed

    def _save_unmapped_log(self):
        """将无法映射的基因符号写入日志（按出现次数降序）。"""
        if not self._unmapped:
            logger.info("No unmapped genes — log not written.")
            return

        sorted_genes = sorted(
            self._unmapped.items(), key=lambda x: x[1], reverse=True
        )
        lines = ["symbol\tcount"]
        lines.extend(f"{sym}\t{cnt}" for sym, cnt in sorted_genes)
        UNMAPPED_GENES_LOG.write_text("\n".join(lines), encoding="utf-8")
        logger.info(
            "Unmapped genes log: %s (%d entries)",
            UNMAPPED_GENES_LOG, len(sorted_genes),
        )


# =====================================================================
# 直接运行入口
# =====================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    validator = GeneValidator()
    validator.process_all()
