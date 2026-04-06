"""
scripts/run_validation.py — LLM 抽取质量验证（独立于主流水线）

使用方式：在主流水线全部跑完后执行
    python scripts/run_validation.py

功能：
  - 随机抽样 VALIDATION_SAMPLE_RATE 比例的已抽取文献
  - 用 VALIDATION_MODEL（更强模型）独立重新抽取
  - 比对结果，计算 Precision / Recall / F1
  - 验证通过后，用更强模型的结果覆盖原始记录
  - 如中途因网络/额度失败，再次运行会自动续跑未完成的文献
"""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import VALIDATION_MODEL, VALIDATION_SAMPLE_RATE
from pipeline.llm_validator import ExtractionValidator


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )
    logger = logging.getLogger("run_validation")

    logger.info(
        "Validation config: model=%s | sample_rate=%.0f%%",
        VALIDATION_MODEL, VALIDATION_SAMPLE_RATE * 100,
    )

    validator = ExtractionValidator()
    report = validator.validate()

    n = report.get("validated", 0)
    nf = report.get("failed", 0)

    if n > 0:
        logger.info("=" * 60)
        logger.info("VALIDATION SUMMARY")
        logger.info("  Papers validated : %d", n)
        logger.info("  Papers failed    : %d%s", nf,
                     " (will retry on next run)" if nf else "")
        logger.info("  Avg Precision    : %.2f%%", report["avg_precision"] * 100)
        logger.info("  Avg Recall       : %.2f%%", report["avg_recall"] * 100)
        logger.info("  Avg F1           : %.2f%%", report["avg_f1"] * 100)
        logger.info("  Gene Precision   : %.2f%%", report["avg_gene_precision"] * 100)
        logger.info("  Gene Recall      : %.2f%%", report["avg_gene_recall"] * 100)
        fa = report.get("avg_field_agreement", {})
        logger.info("  Field agreement  : tissue=%.0f%% | disease=%.0f%% | subtype=%.0f%%",
                     fa.get("tissue", 0) * 100,
                     fa.get("disease", 0) * 100,
                     fa.get("cell_subtype", 0) * 100)
        low = report.get("low_quality_papers", [])
        if low:
            logger.warning("  Low quality (F1<0.5): %s",
                           ", ".join(p["pmcid"] for p in low))
        logger.info("=" * 60)
    elif nf > 0:
        logger.warning(
            "All %d papers failed. Check API key/quota, then re-run this script to retry.",
            nf,
        )
    else:
        logger.info("No papers to validate (all done or no extracted data).")


if __name__ == "__main__":
    main()
