"""
pipeline/fetcher.py — NCBI E-utilities 文献批量获取模块

流程：ESearch（检索 PMC ID 列表）→ 过滤已下载 → EFetch（批量下载全文 XML）→ 拆分保存
支持断点续传、Pilot 模式、速率控制。
"""

import json
import time
import logging
from typing import Optional
from xml.etree import ElementTree as ET

import requests
from tqdm import tqdm

from config.settings import (
    NCBI_API_KEY,
    NCBI_BASE_URL,
    NCBI_SEARCH_TERM,
    NCBI_DB,
    NCBI_RETMAX,
    NCBI_BATCH_SIZE,
    NCBI_RATE_LIMIT,
    NCBI_MAX_RETRIES,
    NCBI_RETRY_DELAY,
    RAW_XML_DIR,
    FETCHED_PMIDS_FILE,
    PILOT_MODE,
    PILOT_SIZE,
    ensure_dirs,
)

logger = logging.getLogger(__name__)


class NCBIFetcher:
    """NCBI E-utilities 文献获取器：搜索 PMC 并下载全文 XML。"""

    def __init__(self):
        self.session = requests.Session()
        self.session.params = {"api_key": NCBI_API_KEY}
        self.min_interval = 1.0 / NCBI_RATE_LIMIT
        self._last_request_time = 0.0
        ensure_dirs()

    # -----------------------------------------------------------------
    # HTTP 基础层
    # -----------------------------------------------------------------

    def _rate_limit(self):
        """遵守 NCBI 速率限制，两次请求间保持最小间隔。"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_time = time.time()

    def _get(
        self,
        url: str,
        params: dict,
        retries: int = NCBI_MAX_RETRIES,
        timeout: int = 120,
    ) -> requests.Response:
        """带速率限制和指数退避重试的 GET 请求。"""
        for attempt in range(1, retries + 1):
            self._rate_limit()
            try:
                resp = self.session.get(url, params=params, timeout=timeout)
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                wait = NCBI_RETRY_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "Request failed (attempt %d/%d): %s — retrying in %ds",
                    attempt, retries, exc, wait,
                )
                if attempt < retries:
                    time.sleep(wait)
                else:
                    raise

    # -----------------------------------------------------------------
    # ESearch：检索 PMC 文章 ID
    # -----------------------------------------------------------------

    def search(self, term: Optional[str] = None) -> list[str]:
        """
        通过 ESearch 获取所有匹配的 PMC ID。

        返回纯数字 PMC ID 列表（如 ["9012345", "9012346", ...]）。
        """
        term = term or NCBI_SEARCH_TERM
        url = f"{NCBI_BASE_URL}/esearch.fcgi"

        # 第一次请求：获取总数和 WebEnv（服务端历史缓存）
        resp = self._get(url, params={
            "db": NCBI_DB,
            "term": term,
            "retmax": 0,
            "retmode": "json",
            "usehistory": "y",
        })
        data = json.loads(resp.text, strict=False)["esearchresult"]
        total = int(data["count"])
        web_env = data["webenv"]
        query_key = data["querykey"]

        logger.info("ESearch: found %d articles in PMC", total)

        if PILOT_MODE:
            total = min(total, PILOT_SIZE)
            logger.info("Pilot mode ON: limiting to %d articles", total)

        # 分页拉取全部 ID
        all_ids: list[str] = []
        for start in tqdm(
            range(0, total, NCBI_RETMAX),
            desc="ESearch pagination",
            unit="page",
        ):
            batch_size = min(NCBI_RETMAX, total - start)

            for attempt in range(1, NCBI_MAX_RETRIES + 1):
                resp = self._get(url, params={
                    "db": NCBI_DB,
                    "WebEnv": web_env,
                    "query_key": query_key,
                    "retstart": start,
                    "retmax": batch_size,
                    "retmode": "json",
                })
                page_data = json.loads(resp.text, strict=False).get("esearchresult", {})
                ids = page_data.get("idlist")
                if ids is not None:
                    all_ids.extend(ids)
                    break
                logger.warning(
                    "ESearch page %d missing idlist (attempt %d/%d), retrying...",
                    start // NCBI_RETMAX + 1, attempt, NCBI_MAX_RETRIES,
                )
                time.sleep(NCBI_RETRY_DELAY * attempt)
            else:
                logger.error("ESearch page %d failed after %d retries — skipping",
                             start // NCBI_RETMAX + 1, NCBI_MAX_RETRIES)

        logger.info("Collected %d PMC IDs", len(all_ids))
        return all_ids

    # -----------------------------------------------------------------
    # EFetch：批量下载全文 XML
    # -----------------------------------------------------------------

    def fetch_batch(self, pmc_ids: list[str]) -> dict[str, str]:
        """
        批量下载一组 PMC 文章的全文 XML。

        参数:
            pmc_ids: 纯数字 PMC ID 列表

        返回:
            {pmcid: xml_string} 字典
        """
        url = f"{NCBI_BASE_URL}/efetch.fcgi"
        resp = self._get(
            url,
            params={
                "db": NCBI_DB,
                "id": ",".join(pmc_ids),
                "retmode": "xml",
            },
            timeout=180,
        )
        return self._split_articles(resp.content, pmc_ids)

    def _split_articles(
        self, xml_bytes: bytes, requested_ids: list[str]
    ) -> dict[str, str]:
        """将 <pmc-articleset> 响应拆分为单篇 <article> XML 字符串。"""
        results: dict[str, str] = {}
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            logger.error("Failed to parse EFetch XML response: %s", exc)
            return results

        articles = root.findall(".//article") if root.tag != "article" else [root]

        for article in articles:
            pmcid = self._extract_pmcid(article)
            if pmcid:
                xml_str = ET.tostring(article, encoding="unicode")
                results[pmcid] = xml_str

        fetched_set = set(results.keys())
        missing = set(requested_ids) - fetched_set
        if missing:
            logger.warning(
                "EFetch: %d/%d articles missing in response: %s",
                len(missing), len(requested_ids), missing,
            )

        return results

    @staticmethod
    def _extract_pmcid(article_element: ET.Element) -> Optional[str]:
        """从 <article> 节点提取纯数字 PMC ID（兼容新旧 NCBI XML 格式）。"""
        for aid in article_element.iter("article-id"):
            pid_type = aid.get("pub-id-type", "")
            text = (aid.text or "").strip()
            if pid_type in ("pmc", "pmcaid"):
                return text
            if pid_type == "pmcid":
                return text.removeprefix("PMC")
        return None

    # -----------------------------------------------------------------
    # 持久化：断点续传
    # -----------------------------------------------------------------

    def load_fetched_ids(self) -> set[str]:
        """加载已成功下载的 PMC ID 集合。"""
        if not FETCHED_PMIDS_FILE.exists():
            return set()
        text = FETCHED_PMIDS_FILE.read_text(encoding="utf-8").strip()
        if not text:
            return set()
        return set(text.splitlines())

    def _append_fetched_id(self, pmcid: str):
        """将下载完成的 PMC ID 追加到记录文件。"""
        with open(FETCHED_PMIDS_FILE, "a", encoding="utf-8") as fh:
            fh.write(pmcid + "\n")

    def _save_xml(self, pmcid: str, xml_content: str):
        """保存单篇文章 XML 到 data/raw_xml/PMC{id}.xml。"""
        path = RAW_XML_DIR / f"PMC{pmcid}.xml"
        path.write_text(xml_content, encoding="utf-8")

    # -----------------------------------------------------------------
    # 主流程
    # -----------------------------------------------------------------

    def run(self) -> int:
        """
        执行完整的文献获取流程。

        返回本次新下载的文章数量。
        """
        logger.info("=" * 60)
        logger.info("NCBI Data Fetcher — Starting")
        logger.info("=" * 60)

        # Step 1: 检索
        all_ids = self.search()
        if not all_ids:
            logger.info("No articles matched the search query.")
            return 0

        # Step 2: 过滤已下载
        fetched_ids = self.load_fetched_ids()
        new_ids = [pid for pid in all_ids if pid not in fetched_ids]
        logger.info(
            "Already on disk: %d | New to download: %d",
            len(fetched_ids), len(new_ids),
        )

        if not new_ids:
            logger.info("All articles already downloaded. Nothing to do.")
            return 0

        # Step 3: 分批下载
        total_saved = 0
        batches = [
            new_ids[i : i + NCBI_BATCH_SIZE]
            for i in range(0, len(new_ids), NCBI_BATCH_SIZE)
        ]

        for batch_ids in tqdm(batches, desc="Downloading batches", unit="batch"):
            try:
                articles = self.fetch_batch(batch_ids)
            except Exception:
                logger.exception(
                    "Batch download failed for %d articles — skipping",
                    len(batch_ids),
                )
                continue

            for pmcid, xml_str in articles.items():
                self._save_xml(pmcid, xml_str)
                self._append_fetched_id(pmcid)
                total_saved += 1

        total_on_disk = len(self.load_fetched_ids())
        logger.info("=" * 60)
        logger.info(
            "Fetching complete. New: %d | Total on disk: %d",
            total_saved, total_on_disk,
        )
        logger.info("=" * 60)
        return total_saved


# =====================================================================
# 直接运行入口
# =====================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    fetcher = NCBIFetcher()
    fetcher.run()
