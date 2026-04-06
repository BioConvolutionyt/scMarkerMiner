"""
pipeline/parser.py — PMC JATS-XML 文本预处理模块

流程：读取 data/raw_xml/*.xml → 提取元数据 + Abstract/Results/Methods/Tables
     → 表格转 Markdown → 清洗降噪 → 按优先级拼接并截断 → 保存 JSON 到 data/processed/
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

from lxml import etree
from tqdm import tqdm

from config.settings import (
    RAW_XML_DIR,
    PROCESSED_DIR,
    TEXT_MAX_TOKENS,
    TEXT_MAX_TABLE_ROWS,
    ensure_dirs,
)

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 4

RESULTS_RE = re.compile(
    r"^(results?|findings?|results?\s+and\s+discussion)", re.IGNORECASE
)
METHODS_RE = re.compile(
    r"^(methods?|materials?\s+and\s+methods?|experimental\s+procedures?)",
    re.IGNORECASE,
)

SKIP_TAGS = frozenset({
    "fig", "graphic", "inline-graphic", "media",
    "inline-formula", "disp-formula", "tex-math",
})
BLOCK_TAGS = frozenset({"p", "sec", "title", "abstract", "list-item", "caption"})


class PMCParser:
    """PMC JATS-XML 解析器：将全文 XML 转换为 LLM 可消费的干净文本。"""

    def __init__(self):
        self.xml_parser = etree.XMLParser(
            recover=True,
            remove_blank_text=True,
            remove_comments=True,
        )
        ensure_dirs()

    # =================================================================
    # 公开接口
    # =================================================================

    def parse_file(self, xml_path: Path) -> Optional[dict]:
        """
        解析单篇 PMC XML 文件。

        返回字典包含元数据、各节原文、组合后的 clean_text，
        或解析失败时返回 None。
        """
        try:
            tree = etree.parse(str(xml_path), self.xml_parser)
            root = tree.getroot()
        except etree.Error as exc:
            logger.error("XML parse error [%s]: %s", xml_path.name, exc)
            return None

        self._strip_namespaces(root)

        metadata = self._extract_metadata(root)
        abstract = self._extract_abstract(root)
        results = self._extract_results(root)
        methods = self._extract_methods(root)
        tables_md = self._extract_tables(root)

        clean_text = self._assemble_text(abstract, results, methods, tables_md)

        return {
            **metadata,
            "abstract": abstract,
            "results": results,
            "methods": methods,
            "tables_md": tables_md,
            "clean_text": clean_text,
            "char_count": len(clean_text),
            "estimated_tokens": len(clean_text) // CHARS_PER_TOKEN,
        }

    def process_all(self, limit: int = 0) -> int:
        """
        批量处理 data/raw_xml/ 下全部 XML。
        自动跳过已存在于 data/processed/ 的文件。

        参数:
            limit: 本次最多处理的新文件数，0 = 不限制。

        返回本次新处理的文件数。
        """
        xml_files = sorted(RAW_XML_DIR.glob("PMC*.xml"))
        if not xml_files:
            logger.warning("No XML files found in %s", RAW_XML_DIR)
            return 0

        to_process = [
            fp for fp in xml_files
            if not (PROCESSED_DIR / f"{fp.stem}.json").exists()
        ]
        if limit > 0:
            to_process = to_process[:limit]

        logger.info(
            "Parsing queue: %d total | %d done | %d pending this run",
            len(xml_files), len(xml_files) - len(to_process), len(to_process),
        )
        if not to_process:
            return 0

        processed = failed = 0

        for xml_path in tqdm(to_process, desc="Parsing XML", unit="file"):
            result = self.parse_file(xml_path)
            if result is None:
                failed += 1
                continue

            out_path = PROCESSED_DIR / f"{xml_path.stem}.json"
            out_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            processed += 1

        logger.info(
            "Parsing complete — Processed: %d | Failed: %d",
            processed, failed,
        )
        return processed

    # =================================================================
    # 元数据提取
    # =================================================================

    def _extract_metadata(self, root) -> dict:
        pmcid = pmid = title = journal = None
        year = None

        for aid in root.iter("article-id"):
            pub_type = aid.get("pub-id-type", "")
            text = (aid.text or "").strip()
            if pub_type in ("pmc", "pmcaid"):
                pmcid = text
            elif pub_type == "pmcid":
                pmcid = text.removeprefix("PMC")
            elif pub_type == "pmid":
                pmid = text

        title_el = root.find(".//article-title")
        if title_el is not None:
            title = self._get_text(title_el)

        journal_el = root.find(".//journal-title")
        if journal_el is not None:
            journal = self._get_text(journal_el)

        for dtype in ("epub", "ppub", "pub", "collection"):
            pd = root.find(f".//pub-date[@pub-type='{dtype}']")
            if pd is None:
                pd = root.find(f".//pub-date[@date-type='{dtype}']")
            if pd is not None:
                y = pd.find("year")
                if y is not None and y.text:
                    year = int(y.text.strip())
                    break

        return {
            "pmcid": pmcid,
            "pmid": pmid,
            "title": title or "Untitled",
            "journal": journal or "Unknown",
            "year": year,
        }

    # =================================================================
    # 节区提取
    # =================================================================

    def _extract_abstract(self, root) -> str:
        el = root.find(".//abstract")
        return self._get_text(el) if el is not None else ""

    def _extract_results(self, root) -> str:
        return self._extract_body_section(root, RESULTS_RE)

    def _extract_methods(self, root) -> str:
        return self._extract_body_section(root, METHODS_RE)

    def _extract_body_section(self, root, pattern: re.Pattern) -> str:
        """从 <body> 的直接 <sec> 子节点中查找标题匹配 pattern 的节区。"""
        body = root.find(".//body")
        if body is None:
            return ""

        parts: list[str] = []
        for sec in body.findall("sec"):
            if self._section_matches(sec, pattern):
                parts.append(self._get_text(sec))
        return "\n\n".join(parts)

    @staticmethod
    def _section_matches(sec, pattern: re.Pattern) -> bool:
        """检查 <sec> 的标题或 sec-type 属性是否匹配给定模式。"""
        sec_type = sec.get("sec-type", "")
        if sec_type and pattern.match(sec_type):
            return True
        title_el = sec.find("title")
        if title_el is not None and title_el.text:
            return bool(pattern.match(title_el.text.strip()))
        return False

    # =================================================================
    # 表格 → Markdown
    # =================================================================

    def _extract_tables(self, root) -> str:
        wraps = root.findall(".//table-wrap")
        if not wraps:
            return ""
        md_parts = [self._table_wrap_to_md(tw) for tw in wraps]
        return "\n\n".join(p for p in md_parts if p)

    def _table_wrap_to_md(self, tw) -> str:
        """将单个 <table-wrap> 转为 Markdown 表格字符串。"""
        label_el = tw.find("label")
        label = self._get_text(label_el) if label_el is not None else ""

        caption_el = tw.find(".//caption")
        caption = self._get_text(caption_el) if caption_el is not None else ""

        header = f"**{label}"
        if caption:
            header += f": {caption}"
        header = header.rstrip() + "**"

        table_el = tw.find(".//table")
        if table_el is None:
            return ""

        rows = self._parse_table_rows(table_el)
        if not rows:
            return ""

        truncated = False
        if len(rows) > TEXT_MAX_TABLE_ROWS + 1:
            rows = rows[: TEXT_MAX_TABLE_ROWS + 1]
            truncated = True

        n_cols = len(rows[0])
        lines = [header]
        lines.append("| " + " | ".join(rows[0]) + " |")
        lines.append("| " + " | ".join("---" for _ in range(n_cols)) + " |")

        for row in rows[1:]:
            padded = (row + [""] * n_cols)[:n_cols]
            lines.append("| " + " | ".join(padded) + " |")

        if truncated:
            lines.append(f"| *(truncated — >{TEXT_MAX_TABLE_ROWS} rows)* |")

        return "\n".join(lines)

    def _parse_table_rows(self, table_el) -> list[list[str]]:
        """解析 <table> 为二维文本列表 [[cell, ...], ...]。"""
        rows: list[list[str]] = []

        thead = table_el.find("thead")
        tbody = table_el.find("tbody")

        if thead is not None or tbody is not None:
            for section in (thead, tbody):
                if section is None:
                    continue
                for tr in section.findall("tr"):
                    cells = self._parse_row(tr)
                    if cells:
                        rows.append(cells)
        else:
            for tr in table_el.findall(".//tr"):
                cells = self._parse_row(tr)
                if cells:
                    rows.append(cells)

        return rows

    def _parse_row(self, tr) -> list[str]:
        """解析 <tr> 中的 <th>/<td> 为字符串列表。"""
        cells: list[str] = []
        for cell in tr:
            if cell.tag in ("th", "td"):
                text = self._get_text(cell).replace("|", "/")
                text = " ".join(text.split())
                cells.append(text)
        return cells

    # =================================================================
    # 文本清洗
    # =================================================================

    def _get_text(self, element) -> str:
        """递归提取纯文本，跳过噪声节点（引用、图片、公式）。"""
        parts: list[str] = []
        self._collect_text(element, parts)
        return re.sub(r"\s+", " ", "".join(parts)).strip()

    def _collect_text(self, el, buf: list[str]):
        tag = el.tag if isinstance(el.tag, str) else ""

        if tag in SKIP_TAGS:
            if el.tail:
                buf.append(el.tail)
            return

        if tag == "xref" and el.get("ref-type") == "bibr":
            if el.tail:
                buf.append(el.tail)
            return

        if el.text:
            buf.append(el.text)

        for child in el:
            self._collect_text(child, buf)

        if tag in BLOCK_TAGS:
            buf.append("\n")

        if el.tail:
            buf.append(el.tail)

    # =================================================================
    # 文本拼接与长度控制
    # =================================================================

    def _assemble_text(
        self,
        abstract: str,
        results: str,
        methods: str,
        tables_md: str,
    ) -> str:
        """
        按优先级拼接：Abstract → Tables → Results → Methods。
        总长度控制在 TEXT_MAX_TOKENS 以内。

        表格优先于 Results，因为表格中的 Marker 信息密度通常最高。
        """
        max_chars = TEXT_MAX_TOKENS * CHARS_PER_TOKEN
        sections: list[tuple[str, str]] = [
            ("Abstract", abstract),
            ("Tables", tables_md),
            ("Results", results),
            ("Methods", methods),
        ]

        parts: list[str] = []
        remaining = max_chars

        for label, text in sections:
            if not text or remaining <= 200:
                continue
            block = f"[{label}]\n{text}"
            if len(block) > remaining:
                block = block[:remaining] + " ..."
            parts.append(block)
            remaining -= len(block)

        return "\n\n".join(parts).strip()

    # =================================================================
    # 工具
    # =================================================================

    @staticmethod
    def _strip_namespaces(root):
        """移除 XML 命名空间，简化后续 XPath。"""
        for el in root.iter():
            if isinstance(el.tag, str) and "{" in el.tag:
                el.tag = el.tag.split("}", 1)[1]
            for key in list(el.attrib):
                if "{" in key:
                    el.attrib[key.split("}", 1)[1]] = el.attrib.pop(key)


# =====================================================================
# 直接运行入口
# =====================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = PMCParser()
    parser.process_all()
