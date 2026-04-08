"""
Cell Marker Database — 全局配置模块

所有可配置项集中定义于此文件，通过环境变量覆盖敏感信息（API Key、数据库密码等）。
使用方式：from config.settings import *
"""

import os
from pathlib import Path

# =============================================================================
# 项目路径
# =============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_XML_DIR = DATA_DIR / "raw_xml"
PROCESSED_DIR = DATA_DIR / "processed"
EXTRACTED_DIR = DATA_DIR / "extracted"
VALIDATED_DIR = DATA_DIR / "validated"
LOG_DIR = DATA_DIR / "logs"

# =============================================================================
# NCBI E-utilities 配置
# =============================================================================
NCBI_API_KEY = os.getenv("NCBI_API_KEY")
NCBI_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_SEARCH_TERM = (
    "single-cell[Title/Abstract] AND "
    "(Randomized Controlled Trial[pt] OR Clinical Trial[pt] OR Systematic Review[pt]) AND "
    "2012:2026[pdat] AND "
    "open access[filter]"
)
NCBI_DB = "pmc"
NCBI_RETMAX = 500
NCBI_BATCH_SIZE = 50
NCBI_RATE_LIMIT = 10
NCBI_MAX_RETRIES = 3
NCBI_RETRY_DELAY = 2

FETCHED_PMIDS_FILE = DATA_DIR / "fetched_pmids.txt"

# =============================================================================
# OpenAI API 配置
# =============================================================================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
OPENAI_MODEL = "openai/gpt-5.4-mini"
OPENAI_TEMPERATURE = 0
OPENAI_MAX_TOKENS = 12000
OPENAI_TIMEOUT = 120
OPENAI_MAX_RETRIES = 3
OPENAI_CONCURRENT_LIMIT = 5

VALIDATION_MODEL = "openai/gpt-5.4"
VALIDATION_SAMPLE_RATE = 0.05

# =============================================================================
# MySQL 数据库配置
# =============================================================================
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME", "scmarkerminer")
DB_CHARSET = "utf8mb4"
DB_SSL = os.getenv("DB_SSL", "0") == "1"

SQLALCHEMY_DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    f"?charset={DB_CHARSET}"
)
SQLALCHEMY_ECHO = False
SQLALCHEMY_POOL_SIZE = 10

# =============================================================================
# 流水线配置
# =============================================================================
PILOT_MODE = False
PILOT_SIZE = 100
BATCH_LIMIT = int(os.getenv("BATCH_LIMIT", "0"))  # 每次运行最多处理的文献数，0 = 不限制

TEXT_MAX_TOKENS = 10000
TEXT_MAX_TABLE_ROWS = 50
TEXT_SECTIONS_PRIORITY = ["abstract", "results", "tables", "methods"]

# =============================================================================
# HGNC 基因符号标准化
# =============================================================================
HGNC_COMPLETE_SET_URL = (
    "https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt"
)
HGNC_CACHE_FILE = DATA_DIR / "hgnc_complete_set.txt"
UNMAPPED_GENES_LOG = LOG_DIR / "unmapped_genes.log"

# =============================================================================
# LLM System Prompt
# =============================================================================
EXTRACTION_SYSTEM_PROMPT = """You are a senior bioinformatics expert specializing in single-cell RNA sequencing (scRNA-seq) data analysis. Your task is to extract cell type marker gene information from scientific literature.

## Task
From the provided text, extract ALL gene markers used for single-cell transcriptomic cell type annotation.

## Rules
1. Only extract markers from HUMAN (Homo sapiens) samples. Ignore mouse, rat, or other species data.
2. Only extract GENE-LEVEL markers. Use official HUGO Gene Symbols (e.g., CD3D, CD8A, FOXP3). Do NOT output protein names, antibody names, or surface antigen labels.
3. If a single marker is associated with multiple cell types, create SEPARATE entries for each.
4. If no disease context is mentioned, set disease to "Normal".
5. If no tissue context is mentioned, set tissue to "Not specified".
6. Only extract markers that the authors explicitly used or validated for cell type annotation/identification.
7. Do NOT extract markers from bulk RNA-seq, proteomics, or non-single-cell experiments.
8. Do NOT fabricate or infer markers not explicitly stated in the text.

## CRITICAL — Naming Standards (you MUST follow)

### ABSOLUTE RULE: NO ABBREVIATIONS, STANDARD PUNCTUATION
You MUST always output FULL names. NEVER use abbreviations or acronyms in ANY field.
Use ONLY standard ASCII hyphens (-) for compound words. NEVER use en-dash (–), em-dash (—), or underscores (_).
  WRONG: "Granulocyte–macrophage progenitor", "Immune_fibroblast cell"
  RIGHT: "Granulocyte-macrophage progenitor", "Immune fibroblast cell"
- cell_type / cell_subtype:
  WRONG → RIGHT: "CAF" → "Cancer-associated fibroblast", "MDSC" → "Myeloid-derived suppressor cell",
  "OPC" → "Oligodendrocyte precursor cell", "ILC" → "Innate lymphoid cell",
  "MAIT" → "MAIT cell", "pDC" → "Plasmacytoid dendritic cell", "cDC" → "Conventional dendritic cell",
  "Treg" → "Regulatory T cell", "GMP" → "Granulocyte-monocyte progenitor",
  "TAM" → "Tumor-associated macrophage", "LSC" → "Leukemic stem cell"
- tissue:
  WRONG → RIGHT: "PBMC" → "Blood", "CSF" → "Cerebrospinal fluid", "PFC" → "Brain", "NAc" → "Nucleus accumbens"
- disease:
  WRONG → RIGHT: "CRC" → "Colorectal cancer", "NSCLC" → "Non-small cell lung cancer",
  "COPD" → "Chronic obstructive pulmonary disease", "PDAC" → "Pancreatic ductal adenocarcinoma",
  "SLE" → "Systemic lupus erythematosus", "AML" → "Acute myeloid leukemia",
  "HCC" → "Hepatocellular carcinoma", "NAFLD" → "Non-alcoholic fatty liver disease",
  "SCZ" → "Schizophrenia", "ALS" → "Amyotrophic lateral sclerosis", "HIV" → "HIV infection",
  "MDS" → "Myelodysplastic syndrome", "ARDS" → "Acute respiratory distress syndrome"

### cell_type field:
- Must be a real biological CELL TYPE, never a disease, tissue, pathway, process, or molecule.
- WRONG: "Colorectal Cancer", "Glioblastoma", "Immune response", "MHC II", "Proliferation"
- Each entry must contain EXACTLY ONE cell type. NEVER combine with "/" or "and".
  If a marker is shared by multiple cell types, create SEPARATE entries for each.
  WRONG: "T/NK cell", "stem/progenitor cell", "Monocyte/Macrophage"
  RIGHT: Create one entry with cell_type="T cell" AND another with cell_type="NK cell".
- NEVER use generic "Cancer cell", "Tumor cell", or "Malignant cell". Use the SPECIFIC cell type instead:
  WRONG → RIGHT: "Cancer cell" → "Glioma cell", "Melanoma cell", "Leukemic cell", "Osteosarcoma cell", etc.
  If the paper does not specify the exact malignant cell type, use the disease context to infer it.
- Always use SINGULAR form: "T cell" not "T cells", "Macrophage" not "Macrophages".
- Use broad canonical names. Map specific subtypes to the broad type in cell_type, put specifics in cell_subtype.
  Examples: CD8+ T cell → cell_type="T cell", cell_subtype="CD8+ T cell"
            Regulatory T cell → cell_type="T cell", cell_subtype="Regulatory T cell"
            M2 macrophage → cell_type="Macrophage", cell_subtype="M2 macrophage"
- Standard names: "T cell", "B cell", "Macrophage", "Monocyte", "Dendritic cell", "NK cell",
  "Neutrophil", "Fibroblast", "Epithelial cell", "Endothelial cell", "Mast cell", "Plasma cell",
  "Astrocyte", "Microglia", "Oligodendrocyte", "Neuron", "Hepatocyte", "Pericyte", "Stellate cell",
  "Smooth muscle cell", "Cancer-associated fibroblast", "Mesenchymal stem cell", etc.

### tissue field:
- Must be a real anatomical tissue or organ: "Lung", "Liver", "Brain", "Kidney", "Blood", etc.
- WRONG: "Tumor", "Tissue", "Serum", "Stool", "Urine" — these are NOT tissues.
- Use the canonical organ name: "Colon" not "Colonic tissue", "Breast" not "Breast tissue".
- If unclear, set to "Not specified".

### disease field:
- Use the FULL disease name, never abbreviations (see rule above).
- Use consistent title case: "Ulcerative colitis", "Non-small cell lung cancer".
- If the study subjects are healthy controls, use "Normal".

### marker field:
- Must be a single, valid HUGO gene symbol (e.g., CD3D, FOXP3, HLA-DRA).
- NEVER output descriptive text, sentences, or phrases as a marker value.
  WRONG: "TCR-related transcriptional cluster markers", "Not identified", "Multiple genes"
  RIGHT: "CD3D", "CD3E", "TRAC" (create separate entries for each gene)
- If no specific gene symbol can be identified, do NOT create the entry at all.

## Output Format
Return a JSON object with the following structure:
{
  "markers": [
    {
      "cell_type": "broad cell type (singular, e.g., T cell, B cell, Macrophage)",
      "cell_subtype": "specific subtype if mentioned (e.g., CD8+ T cell), or null",
      "marker": "HUGO gene symbol (e.g., CD8A, MS4A1, FOXP3)",
      "tissue": "anatomical tissue/organ (e.g., Lung, Liver, Blood)",
      "disease": "full disease name (e.g., Lung adenocarcinoma, Ulcerative colitis, Normal)"
    }
  ]
}

If the text contains NO relevant single-cell marker information, return: {"markers": []}
"""

# =============================================================================
# FastAPI 后端配置
# =============================================================================
API_HOST = "0.0.0.0"
API_PORT = 8000
API_CORS_ORIGINS = ["http://localhost:5173", "http://localhost:3000", "*"]
API_PAGE_SIZE = 20
API_MAX_PAGE_SIZE = 200

# =============================================================================
# 导出配置
# =============================================================================
EXPORT_MAX_ROWS = 50000
EXPORT_FORMATS = ["csv", "xlsx"]

# =============================================================================
# 工具函数
# =============================================================================

def ensure_dirs():
    """创建所有必要的数据目录。"""
    for d in [RAW_XML_DIR, PROCESSED_DIR, EXTRACTED_DIR, VALIDATED_DIR, LOG_DIR]:
        d.mkdir(parents=True, exist_ok=True)
