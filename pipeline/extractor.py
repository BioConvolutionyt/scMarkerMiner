"""
pipeline/extractor.py — LLM 知识抽取 Agent

使用 OpenAI GPT-5.4-mini 从预处理文本中提取单细胞 Marker 信息。
异步并发调用 + 信号量控速 + 指数退避重试 + 结构化 JSON 输出。
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI
from tqdm import tqdm

from config.settings import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    OPENAI_TEMPERATURE,
    OPENAI_MAX_TOKENS,
    OPENAI_TIMEOUT,
    OPENAI_MAX_RETRIES,
    OPENAI_CONCURRENT_LIMIT,
    EXTRACTION_SYSTEM_PROMPT,
    PROCESSED_DIR,
    EXTRACTED_DIR,
    ensure_dirs,
)

logger = logging.getLogger(__name__)

REQUIRED_MARKER_FIELDS = {"cell_type", "marker"}
ALL_MARKER_FIELDS = {"cell_type", "cell_subtype", "marker", "tissue", "disease"}


class MarkerExtractor:
    """基于 LLM 的细胞 Marker 结构化抽取器。"""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL,
            timeout=OPENAI_TIMEOUT,
        )
        self.model = OPENAI_MODEL
        ensure_dirs()

    # =================================================================
    # 单篇抽取
    # =================================================================

    async def extract_one(
        self,
        doc: dict,
        semaphore: asyncio.Semaphore,
    ) -> Optional[dict]:
        """
        对单篇文献调用 LLM 进行 Marker 抽取。

        参数:
            doc: 预处理 JSON（必须含 clean_text）
            semaphore: 并发控制信号量

        返回:
            抽取结果字典，或 None（失败时）
        """
        pmcid = doc.get("pmcid", "unknown")
        clean_text = doc.get("clean_text", "")

        if not clean_text.strip():
            logger.warning("[PMC%s] Empty text — skipped", pmcid)
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

                raw_content = response.choices[0].message.content
                parsed = json.loads(raw_content)
                markers_raw = parsed.get("markers", [])
                markers_valid = self._validate_markers(markers_raw, pmcid)

                return {
                    "pmcid": pmcid,
                    "pmid": doc.get("pmid"),
                    "title": doc.get("title"),
                    "markers": markers_valid,
                    "raw_marker_count": len(markers_raw),
                    "valid_marker_count": len(markers_valid),
                    "model": self.model,
                    "usage": {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                    },
                    "extracted_at": datetime.now(timezone.utc).isoformat(),
                }

            except json.JSONDecodeError as exc:
                logger.warning(
                    "[PMC%s] Invalid JSON response (attempt %d/%d): %s",
                    pmcid, attempt, OPENAI_MAX_RETRIES, exc,
                )
            except Exception as exc:
                wait = 2 ** attempt
                logger.warning(
                    "[PMC%s] API error (attempt %d/%d): %s — retry in %ds",
                    pmcid, attempt, OPENAI_MAX_RETRIES, exc, wait,
                )
                if attempt < OPENAI_MAX_RETRIES:
                    await asyncio.sleep(wait)

        logger.error("[PMC%s] All %d attempts failed", pmcid, OPENAI_MAX_RETRIES)
        return None

    # =================================================================
    # 结果校验
    # =================================================================

    @staticmethod
    def _validate_markers(markers: list, pmcid: str) -> list[dict]:
        """
        校验 LLM 返回的 marker 列表：
        - 必须是 dict
        - 必须包含 cell_type 和 marker 字段
        - 清洗空白、统一字段
        """
        valid: list[dict] = []
        for idx, entry in enumerate(markers):
            if not isinstance(entry, dict):
                logger.debug("[PMC%s] marker[%d] not a dict — dropped", pmcid, idx)
                continue
            if not all(entry.get(f) for f in REQUIRED_MARKER_FIELDS):
                logger.debug(
                    "[PMC%s] marker[%d] missing required field — dropped", pmcid, idx
                )
                continue

            cleaned = {}
            for field in ALL_MARKER_FIELDS:
                val = entry.get(field)
                if isinstance(val, str) and val.strip():
                    cleaned[field] = val.strip()
                else:
                    cleaned[field] = None
            valid.append(cleaned)
        return valid

    # =================================================================
    # 批量处理
    # =================================================================

    async def _extract_all_async(self, limit: int = 0) -> int:
        """异步并发处理全部预处理文件。"""
        json_files = sorted(PROCESSED_DIR.glob("PMC*.json"))
        if not json_files:
            logger.warning("No processed files found in %s", PROCESSED_DIR)
            return 0

        to_process = [
            fp for fp in json_files
            if not (EXTRACTED_DIR / fp.name).exists()
        ]
        if limit > 0:
            to_process = to_process[:limit]

        logger.info(
            "Extraction queue: %d total | %d done | %d pending this run",
            len(json_files),
            len(json_files) - len(to_process),
            len(to_process),
        )
        if not to_process:
            logger.info("All files already extracted. Nothing to do.")
            return 0

        semaphore = asyncio.Semaphore(OPENAI_CONCURRENT_LIMIT)

        async def _task(fp: Path) -> Optional[dict]:
            try:
                doc = json.loads(fp.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.error("Cannot read %s: %s", fp.name, exc)
                return None
            return await self.extract_one(doc, semaphore)

        tasks = [_task(fp) for fp in to_process]

        saved = 0
        total_markers = 0
        total_tokens = 0

        pbar = tqdm(total=len(tasks), desc="LLM extraction", unit="paper")
        for future in asyncio.as_completed(tasks):
            result = await future
            pbar.update(1)

            if result is None:
                continue

            out_path = EXTRACTED_DIR / f"PMC{result['pmcid']}.json"
            out_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            saved += 1
            total_markers += result["valid_marker_count"]
            total_tokens += result["usage"]["total_tokens"]

        pbar.close()

        logger.info("=" * 50)
        logger.info("Extraction summary")
        logger.info("  Papers processed : %d", saved)
        logger.info("  Total markers    : %d", total_markers)
        logger.info("  Avg markers/paper: %.1f", total_markers / max(saved, 1))
        logger.info("  Total tokens used: %d", total_tokens)
        logger.info("=" * 50)
        return saved

    def process_all(self, limit: int = 0) -> int:
        """同步入口：运行异步批量抽取。limit=0 表示不限制。"""
        return asyncio.run(self._extract_all_async(limit))


# =====================================================================
# 直接运行入口
# =====================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    extractor = MarkerExtractor()
    extractor.process_all()
