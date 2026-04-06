"""
pipeline/llm_validator.py — LLM 抽取结果质量验证模块

验证流程：
  1. 首次运行：随机抽样 VALIDATION_SAMPLE_RATE 比例的文献，生成待验证列表
  2. 用 VALIDATION_MODEL 对相同文本独立重新抽取
  3. 比对两组 markers，计算质量指标（Precision / Recall / F1）
  4. 用验证模型的结果覆盖 data/extracted/ 中的原始记录
  5. 将比对报告（含原始数据备份）保存到 data/validated/
  6. 如中途失败，再次运行会自动续跑未完成的文献

断点续跑机制：
  - 待验证列表保存在 data/logs/validation_pending.json
  - 成功验证的文献从 pending 中移除
  - 失败的文献保留在 pending 中，下次运行自动重试
  - 全部完成后删除 pending 文件
"""

import asyncio
import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI
from tqdm import tqdm

from config.settings import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_TEMPERATURE,
    OPENAI_MAX_TOKENS,
    OPENAI_TIMEOUT,
    OPENAI_MAX_RETRIES,
    OPENAI_CONCURRENT_LIMIT,
    EXTRACTION_SYSTEM_PROMPT,
    VALIDATION_MODEL,
    VALIDATION_SAMPLE_RATE,
    PROCESSED_DIR,
    EXTRACTED_DIR,
    VALIDATED_DIR,
    LOG_DIR,
    ensure_dirs,
)

logger = logging.getLogger(__name__)

PENDING_FILE = LOG_DIR / "validation_pending.json"


# =====================================================================
# 比对逻辑
# =====================================================================

def _marker_key(m: dict) -> tuple[str, str]:
    ct = (m.get("cell_type") or "").strip().lower()
    gene = (m.get("marker") or "").strip().upper()
    return (ct, gene)


def _gene_only_key(m: dict) -> str:
    return (m.get("marker") or "").strip().upper()


def compare_markers(original: list[dict], reference: list[dict]) -> dict:
    """
    比较两组 marker 列表。

    original:  原始抽取模型的输出
    reference: 验证模型的输出（视为更高质量的参考）
    """
    orig_keys = {}
    for m in original:
        k = _marker_key(m)
        if k[1]:
            orig_keys.setdefault(k, m)

    ref_keys = {}
    for m in reference:
        k = _marker_key(m)
        if k[1]:
            ref_keys.setdefault(k, m)

    matched_strict = set(orig_keys) & set(ref_keys)

    orig_genes = {}
    for m in original:
        g = _gene_only_key(m)
        if g:
            orig_genes.setdefault(g, m)

    ref_genes = {}
    for m in reference:
        g = _gene_only_key(m)
        if g:
            ref_genes.setdefault(g, m)

    matched_gene = set(orig_genes) & set(ref_genes)

    n_orig = len(orig_keys)
    n_ref = len(ref_keys)
    n_matched = len(matched_strict)

    precision = n_matched / n_orig if n_orig else 0.0
    recall = n_matched / n_ref if n_ref else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    gene_precision = len(matched_gene) / len(orig_genes) if orig_genes else 0.0
    gene_recall = len(matched_gene) / len(ref_genes) if ref_genes else 0.0

    tissue_agree = disease_agree = subtype_agree = 0
    for k in matched_strict:
        om, rm = orig_keys[k], ref_keys[k]
        if (om.get("tissue") or "").lower() == (rm.get("tissue") or "").lower():
            tissue_agree += 1
        if (om.get("disease") or "").lower() == (rm.get("disease") or "").lower():
            disease_agree += 1
        if (om.get("cell_subtype") or "").lower() == (rm.get("cell_subtype") or "").lower():
            subtype_agree += 1

    n = max(n_matched, 1)

    return {
        "original_count": n_orig,
        "reference_count": n_ref,
        "matched_strict": n_matched,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "gene_only_precision": round(gene_precision, 4),
        "gene_only_recall": round(gene_recall, 4),
        "field_agreement": {
            "tissue": round(tissue_agree / n, 4),
            "disease": round(disease_agree / n, 4),
            "cell_subtype": round(subtype_agree / n, 4),
        },
        "only_in_original": [
            orig_keys[k] for k in list(set(orig_keys) - set(ref_keys))[:10]
        ],
        "only_in_reference": [
            ref_keys[k] for k in list(set(ref_keys) - set(orig_keys))[:10]
        ],
    }


# =====================================================================
# 核心类
# =====================================================================

class ExtractionValidator:
    """使用更强模型对 LLM 抽取结果进行抽样验证，验证通过后覆盖原始记录。"""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL,
            timeout=OPENAI_TIMEOUT,
        )
        self.model = VALIDATION_MODEL
        ensure_dirs()

    # -----------------------------------------------------------------
    # 待验证列表管理（断点续跑）
    # -----------------------------------------------------------------

    def _load_or_create_pending(self) -> list[str]:
        """加载已有待验证列表，或创建新的随机抽样。"""
        already_validated = {fp.stem for fp in VALIDATED_DIR.glob("PMC*.json")}

        if PENDING_FILE.exists():
            try:
                pending = json.loads(PENDING_FILE.read_text("utf-8"))
                remaining = [p for p in pending if p not in already_validated]
                if remaining:
                    logger.info(
                        "Resuming: %d/%d pending papers remaining",
                        len(remaining), len(pending),
                    )
                    self._save_pending(remaining)
                    return remaining
            except Exception:
                pass

        extracted = sorted(EXTRACTED_DIR.glob("PMC*.json"))
        candidates = [fp.stem for fp in extracted if fp.stem not in already_validated]

        if not candidates:
            return []

        sample_size = max(1, int(len(candidates) * VALIDATION_SAMPLE_RATE))
        sampled = random.sample(candidates, min(sample_size, len(candidates)))

        logger.info(
            "New validation round: %d extracted | %d already validated | sampling %d (%.0f%%)",
            len(extracted), len(already_validated), len(sampled),
            VALIDATION_SAMPLE_RATE * 100,
        )
        self._save_pending(sampled)
        return sampled

    @staticmethod
    def _save_pending(pending: list[str]):
        PENDING_FILE.write_text(
            json.dumps(pending, indent=2), encoding="utf-8",
        )

    @staticmethod
    def _clear_pending():
        if PENDING_FILE.exists():
            PENDING_FILE.unlink()

    # -----------------------------------------------------------------
    # LLM 调用
    # -----------------------------------------------------------------

    async def _reextract(
        self, doc: dict, semaphore: asyncio.Semaphore,
    ) -> Optional[list[dict]]:
        """用验证模型独立重新抽取 markers。"""
        pmcid = doc.get("pmcid", "unknown")
        clean_text = doc.get("clean_text", "")
        if not clean_text.strip():
            return None

        user_message = (
            f"PMID: {doc.get('pmid', 'N/A')}\n"
            f"Title: {doc.get('title', 'N/A')}\n\n"
            f"{clean_text}"
        )

        for attempt in range(1, OPENAI_MAX_RETRIES + 1):
            try:
                async with semaphore:
                    response = await self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                            {"role": "user", "content": user_message},
                        ],
                        temperature=OPENAI_TEMPERATURE,
                        max_tokens=OPENAI_MAX_TOKENS,
                        response_format={"type": "json_object"},
                    )
                raw = response.choices[0].message.content
                parsed = json.loads(raw)
                return parsed.get("markers", [])

            except json.JSONDecodeError as exc:
                logger.warning(
                    "[%s] Validation JSON error (attempt %d/%d): %s",
                    pmcid, attempt, OPENAI_MAX_RETRIES, exc,
                )
            except Exception as exc:
                wait = 2 ** attempt
                logger.warning(
                    "[%s] Validation API error (attempt %d/%d): %s — retry in %ds",
                    pmcid, attempt, OPENAI_MAX_RETRIES, exc, wait,
                )
                if attempt < OPENAI_MAX_RETRIES:
                    await asyncio.sleep(wait)

        logger.error("[%s] Validation failed after %d retries", pmcid, OPENAI_MAX_RETRIES)
        return None

    # -----------------------------------------------------------------
    # 主流程
    # -----------------------------------------------------------------

    async def _validate_all_async(self) -> dict:
        pending = self._load_or_create_pending()
        if not pending:
            logger.info("No papers to validate.")
            return {"validated": 0}

        semaphore = asyncio.Semaphore(max(1, OPENAI_CONCURRENT_LIMIT // 2))
        paper_results = []
        succeeded = []
        failed = []

        pbar = tqdm(total=len(pending), desc="LLM validation", unit="paper")
        for pmcid in pending:
            ext_fp = EXTRACTED_DIR / f"{pmcid}.json"
            proc_fp = PROCESSED_DIR / f"{pmcid}.json"

            if not proc_fp.exists() or not ext_fp.exists():
                logger.warning("[%s] Source file missing — skipped", pmcid)
                succeeded.append(pmcid)
                pbar.update(1)
                continue

            try:
                proc_doc = json.loads(proc_fp.read_text("utf-8"))
                ext_doc = json.loads(ext_fp.read_text("utf-8"))
            except Exception as exc:
                logger.error("[%s] File read error: %s", pmcid, exc)
                failed.append(pmcid)
                pbar.update(1)
                continue

            original_markers = ext_doc.get("markers", [])

            ref_markers = await self._reextract(proc_doc, semaphore)
            pbar.update(1)

            if ref_markers is None:
                failed.append(pmcid)
                continue

            comparison = compare_markers(original_markers, ref_markers)
            comparison["pmcid"] = pmcid
            comparison["extraction_model"] = ext_doc.get("model", "unknown")
            comparison["validation_model"] = self.model
            comparison["validated_at"] = datetime.now(timezone.utc).isoformat()
            comparison["original_markers_backup"] = original_markers

            val_path = VALIDATED_DIR / f"{pmcid}.json"
            val_path.write_text(
                json.dumps(comparison, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            ext_doc["markers"] = ref_markers
            ext_doc["valid_marker_count"] = len(ref_markers)
            ext_doc["model"] = self.model
            ext_doc["validated"] = True
            ext_doc["original_model"] = comparison["extraction_model"]
            ext_fp.write_text(
                json.dumps(ext_doc, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            succeeded.append(pmcid)
            paper_results.append(comparison)
            logger.debug(
                "[%s] Validated — F1=%.2f | %d → %d markers",
                pmcid, comparison["f1"],
                comparison["original_count"], comparison["reference_count"],
            )

        pbar.close()

        if failed:
            self._save_pending(failed)
            logger.warning(
                "%d papers failed and will be retried on next run (saved to %s)",
                len(failed), PENDING_FILE,
            )
        else:
            self._clear_pending()
            logger.info("All pending papers validated successfully.")

        summary = self._aggregate(paper_results, len(failed))

        report_path = LOG_DIR / "validation_report.json"
        report_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Validation report saved to %s", report_path)

        return summary

    @staticmethod
    def _aggregate(results: list[dict], n_failed: int) -> dict:
        if not results:
            return {"validated": 0, "failed": n_failed}

        n = len(results)
        avg = lambda key: round(sum(r[key] for r in results) / n, 4)

        low_f1 = [
            {"pmcid": r["pmcid"], "f1": r["f1"],
             "precision": r["precision"], "recall": r["recall"]}
            for r in results if r["f1"] < 0.5
        ]

        return {
            "validated": n,
            "failed": n_failed,
            "avg_precision": avg("precision"),
            "avg_recall": avg("recall"),
            "avg_f1": avg("f1"),
            "avg_gene_precision": avg("gene_only_precision"),
            "avg_gene_recall": avg("gene_only_recall"),
            "avg_field_agreement": {
                "tissue": round(sum(r["field_agreement"]["tissue"] for r in results) / n, 4),
                "disease": round(sum(r["field_agreement"]["disease"] for r in results) / n, 4),
                "cell_subtype": round(sum(r["field_agreement"]["cell_subtype"] for r in results) / n, 4),
            },
            "low_quality_papers": low_f1,
            "per_paper": [
                {
                    "pmcid": r["pmcid"],
                    "precision": r["precision"],
                    "recall": r["recall"],
                    "f1": r["f1"],
                    "original_count": r["original_count"],
                    "reference_count": r["reference_count"],
                    "matched_strict": r["matched_strict"],
                }
                for r in results
            ],
        }

    def validate(self) -> dict:
        """同步入口。"""
        return asyncio.run(self._validate_all_async())


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    v = ExtractionValidator()
    report = v.validate()
    n = report.get("validated", 0)
    nf = report.get("failed", 0)
    if n > 0:
        print(f"\nValidation complete: {n} papers validated, {nf} failed")
        print(f"  Avg Precision: {report['avg_precision']:.2%}")
        print(f"  Avg Recall:    {report['avg_recall']:.2%}")
        print(f"  Avg F1:        {report['avg_f1']:.2%}")
    elif nf > 0:
        print(f"\nAll {nf} papers failed. Check logs and re-run to retry.")
    else:
        print("\nNo papers to validate.")
