"""
pipeline/normalizer.py — 提取结果后处理标准化

对 LLM 返回的 cell_type / cell_subtype / tissue / disease 字段进行：
  1. Unicode 归一化（弯引号 → 直引号, en-dash → 连字符, 乱码清理）
  2. 单复数归一化（B cells → B cell）
  3. 同义词合并（NK cell / Natural Killer cell → NK cell）
  4. 大小写统一
  5. 无效条目过滤（疾病名误入 cell_type 等）
  6. 缩写展开（CRC → Colorectal cancer）
  7. 英美拼写统一（oesophageal → esophageal）
"""

import json
import logging
import re
from collections import Counter, defaultdict
from pathlib import Path

from config.settings import EXTRACTED_DIR, ensure_dirs

logger = logging.getLogger(__name__)


# =====================================================================
# 通用文本预处理
# =====================================================================

_DASH_CHARS = str.maketrans({
    "\u2010": "-",  # ‐ hyphen
    "\u2011": "-",  # ‑ non-breaking hyphen
    "\u2012": "-",  # ‒ figure dash
    "\u2013": "-",  # – en-dash
    "\u2014": "-",  # — em-dash
    "\u2015": "-",  # ― horizontal bar
    "\u2212": "-",  # − minus sign
    "\u00AD": "",   # ­ soft hyphen (remove)
    "\uFE63": "-",  # ﹣ small hyphen-minus
    "\uFF0D": "-",  # － fullwidth hyphen-minus
})

def _normalize_unicode(text: str) -> str:
    """统一 Unicode 变体：弯引号→直引号, 各种 dash→连字符, 下划线→空格, 乱码清理。"""
    text = text.replace("\u2018", "'").replace("\u2019", "'")   # ' '
    text = text.replace("\u201c", '"').replace("\u201d", '"')   # " "
    text = text.translate(_DASH_CHARS)
    text = text.replace("_", " ")
    text = text.replace("\ufffd", "").replace("�", "")
    text = re.sub(r"[\x00-\x1f]+", " ", text)
    text = re.sub(r"  +", " ", text)
    return text.strip()


def _singularize(text: str) -> str:
    """简单的英语复数 → 单数。"""
    low = text.lower()
    if low.endswith("cells") and not low.endswith("stem cells"):
        return text[:-1]
    if low.endswith("cytes") or low.endswith("blasts") or low.endswith("phages"):
        return text
    if low.endswith("mas") and not low.endswith("smas"):
        return text[:-1]
    return text


def _singularize_disease(text: str) -> str:
    """疾病名复数 → 单数 (gliomas→glioma, syndromes→syndrome)。"""
    low = text.lower()
    if low.endswith("omas"):
        return text[:-1]
    if low.endswith("syndromes"):
        return text[:-1]
    if low.endswith("neoplasms"):
        return text[:-1]
    return text


# =====================================================================
# Cell Type
# =====================================================================

CELL_TYPE_SYNONYMS: dict[str, list[str]] = {
    "T cell":               ["T cells", "T lymphocyte", "T lymphocytes",
                             "T cytotoxic", "Cytotoxic cell"],
    "B cell":               ["B cells", "B lymphocyte", "B lymphocytes"],
    "NK cell":              ["NK cells", "Natural Killer cell", "Natural Killer cells",
                             "Natural Killer Cell", "Natural Killer (NK) cell",
                             "Natural Killer T cell"],
    "NKT cell":             ["NKT cells", "NK T cell", "NK-T cell"],
    "Macrophage":           ["Macrophages", "Monocyte-derived macrophage"],
    "Monocyte":             ["Monocytes", "CD14+ monocyte"],
    "Dendritic cell":       ["Dendritic Cell", "Dendritic cells",
                             "Myeloid dendritic cell"],
    "Fibroblast":           ["Fibroblasts"],
    "Epithelial cell":      ["Epithelial cells", "Colonic epithelial cell",
                             "Malignant epithelial cells", "Urothelial cell",
                             "Cancer epithelial", "Normal epithelial cell"],
    "Endothelial cell":     ["Endothelial cells", "Endothelial",
                             "Vascular endothelium", "Vascular endothelial cell"],
    "Neuron":               ["Neuronal", "Neuronal cell", "Mature neuron",
                             "Mature Neuron", "Immature Neuron",
                             "Excitatory neuron", "Inhibitory interneuron",
                             "Deep cortical layer neuron",
                             "Upper cortical layer neuron",
                             "Neurocyte", "Neuro cell"],
    "Astrocyte":            ["Astrocytes"],
    "Myeloid-derived suppressor cell": ["Myeloid-Derived Suppressor Cell", "MDSC"],
    "Myeloid cell":         ["Myeloid cells", "Myeloid"],
    "Mesenchymal stem cell": ["BMSC", "Mesenchymal Stem Cell"],
    "Smooth muscle cell":   ["VSMC", "Vascular smooth muscle cell",
                             "Vascular smooth muscle"],
    "Cancer stem cell":     ["Cancer Stem Cell"],
    "Innate lymphoid cell": ["Innate Lymphoid Cell", "ILC"],
    "Oligodendrocyte":      ["Oligodendrocytes"],
    "Neural progenitor cell": ["Neural progenitor", "Neural Stem Cell",
                               "Intermediate Progenitor Cell",
                               "Ventral progenitor"],
    "Regulatory T cell":    ["Treg", "Tregs", "T reg", "T regulatory cell"],
    "Plasma cell":          ["Plasma cells"],
    "CD8+ T cell":          ["CD8+ T cells", "CD8 T cell", "CD8 + T cell",
                             "Cytotoxic T cell", "Cytotoxic T lymphocyte"],
    "CD4+ T cell":          ["CD4+ T cells", "CD4 T cell", "CD4 + T cell",
                             "Th cell", "Th1 cell", "Th2 cell"],
    "Immune cell":          ["Immune cells", "Lymphocyte", "Immune"],
    "Oligodendrocyte precursor cell": ["OPC", "Oligodendrocyte progenitor cell"],
    "Corneal endothelial cell": ["Corneal Endothelial Cell"],
    "Proximal tubule cell": ["Proximal Tubule", "Proximal Tubule cell",
                             "Proximal tubular cell",
                             "Renal proximal tubule cell"],
    "Retinal pigment epithelial cell": ["Retinal Pigment Epithelium",
                                        "RPE cell"],
    "Blast cell":           ["Blast"],
    "Stromal cell":         ["Stroma cell", "stromal cell", "Stroma"],
    "Interneuron":          ["Interneuron cell"],
    "MAIT cell":            ["MAIT"],
    "Antigen-presenting cell": ["Antigen presenting cell"],
    "Spermatogonium":       ["Spermatogonia"],
    "Lymphatic endothelial cell": ["Lymphatic Endothelial cell"],
    "Granulocyte-monocyte progenitor": ["Granulocyte-macrophage progenitor",
                                        "GMP"],
    "Cancer-associated fibroblast": ["CAF"],
    "Mueller glia":         ["Muller cell", "Muller glia"],
    "Gamma delta T cell":   ["GdT cell"],
    "Lymphoid cell":        ["Lymphoid"],
    "Progenitor cell":      ["Progenitor"],
    "Plasmacytoid dendritic cell": ["pDC"],
    "Conventional dendritic cell": ["cDC"],
    "Leukemic stem cell":   ["Leukaemia stem cell", "LSC"],
    "M2 macrophage":        ["M2 macrophages"],
    "M1 macrophage":        ["M1 macrophages"],
    "Alveolar type II cell": ["Alveolar cell type 2", "Alveolar cell type II",
                              "Alveolar type 2 cell", "AT2 cell",
                              "Pulmonary alveolar type II cell"],
    "Alveolar type I cell": ["Alveolar cell type 1", "Alveolar cell type I",
                             "Alveolar type 1 cell", "AT1 cell",
                             "Pulmonary alveolar type I cell"],
    "Common myeloid progenitor": ["CMP"],
    "Renal tubule cell":    ["Renal tuble cell", "Tubule cell"],
    "Hematopoietic stem cell": ["Hemopoietic stem cell"],
    "Ionocyte":             ["Ionocyte cell"],
    "Cardiac progenitor cell": ["Cardiac progenitor"],
    "Platelet":             ["Platelet cell"],
    "Erythroid cell":       ["Erythroid"],
    "Notochord cell":       ["Notochord"],
    "Muscle cell":          ["Muscle"],
    "Megakaryocyte progenitor": ["MPC"],
    "Preadipocyte":             ["Pre-adipocyte", "Pre adipocyte"],
    "Collecting duct intercalated cell": ["Collecting duct-intercalated cell"],
    "Collecting duct principal cell":    ["Collecting duct-principal cell"],
    "Common lymphoid progenitor cell":   ["Common lymphoid progenitor"],
}

_INVALID_CELL_TYPES = {
    "colorectal cancer", "hepatocellular carcinoma",
    "intrahepatic cholangiocarcinoma",
    "combined hepatocellular-cholangiocarcinoma", "breast cancer",
    "glioblastoma", "proliferation", "mhc ii", "immune response",
    "myelin regulation", "immune checkpoint", "extracellular vesicle",
    "thick ascending limb",
    "cell", "null", "normal", "other cell", "unclassified cell",
    "complement component", "gene", "mucin producing", "chemokine",
    "carcinoma", "glioma", "decidua", "liver", "adipose tissue",
    "embryo", "blastocyst", "choroid plexus", "squamous",
    "differentiation cell", "ribosomal cell", "development",
    "not specified",
    "cancer cell", "cancer cells", "tumor cell", "tumor cells",
    "malignant cell", "neoplastic cell", "differentiated tumor cell",
    "gbm cells", "tumor",
}


# =====================================================================
# Subtype
# =====================================================================

SUBTYPE_SYNONYMS: dict[str, list[str]] = {
    "CD8+ T cell":              ["CD8 T cell", "CD8 + T cell"],
    "CD4+ T cell":              ["CD4 T cell", "CD4 + T cell"],
    "Regulatory T cell":        ["Treg", "Treg cell", "regulatory T cell"],
    "Exhausted T cell":         ["exhausted T cell"],
    "Exhausted CD8+ T cell":    ["exhausted CD8+ T cell"],
    "Naive T cell":             ["Naive T cell"],
    "Naive B cell":             ["naive B cell"],
    "Memory B cell":            ["memory B cell"],
    "Plasmacytoid dendritic cell": ["plasmacytoid dendritic cell", "pDC"],
    "Non-classical monocyte":   ["Non-Classical Monocyte"],
    "Conventional dendritic cell": ["conventional dendritic cell"],
    "CD16+ monocyte":           ["CD16+ Monocyte"],
    "M2 macrophage":            ["M2"],
    "M1 macrophage":            ["M1"],
    "Th1":                      ["Th1 cell"],
    "Th2":                      ["Th2 cell"],
    "Th17":                     ["Th17 cell"],
    "Plasma B cell":            ["Plasma cell"],
    "Cancer-associated fibroblast": ["CAF"],
    "Tumor-associated macrophage": ["TAM"],
    "Tissue-resident memory T cell": ["Tissue Resident Memory T cell"],
}

_INVALID_SUBTYPES = {
    "null", "not specified", "n/a", "none", "na", "",
    "natural killer",
}


# =====================================================================
# Tissue
# =====================================================================

TISSUE_SYNONYMS: dict[str, list[str]] = {
    "Colon":            ["Colonic tissue", "Colonic tissues", "Colorectal",
                         "Colonic biopsies", "Colonic mucosal samples",
                         "Colon transversum", "Colon sigmoideum",
                         "Large intestine"],
    "Brain":            ["Cortex", "Hippocampus", "PFC", "Prefrontal cortex",
                         "Entorhinal cortex", "Midbrain", "Striatum",
                         "Frontal Cortex BA9", "Putamen basal ganglia",
                         "Corpus callosum", "Hypothalamus"],
    "Blood":            ["Peripheral blood", "Serum", "Plasma", "PBMC",
                         "Cord blood"],
    "Bone marrow":      ["Bone Marrow"],
    "Nucleus accumbens": ["NAc"],
    "Central amygdala": ["CeA"],
    "Small intestine":  ["Small Intestine"],
    "Cerebrospinal fluid": ["CSF"],
    "Stomach":          ["Gastric", "Stomach wall"],
    "Kidney":           ["Renal"],
    "Heart":            ["Cardiac"],
    "Breast":           ["Mammary"],
    "Oral cavity":      ["Oral"],
    "Synovium":         ["Synovial"],
    "Intestine":        ["Intestinal", "Gut"],
    "Omentum":          ["Omental"],
    "Gingiva":          ["Gingival"],
    "Pancreas":         ["Pancreatic"],
    "Adrenal gland":    ["Adrenal"],
    "Skeletal muscle":  ["Skeletal Muscle"],
    "Prostate":         ["Prostate transition zone", "Prostate biopsies",
                         "Fresh PCa samples", "Primary PCa samples",
                         "PNI-PCa samples", "PRAD samples"],
    "Pancreatic islets": ["Islet"],
    "Lung":             ["Bronchoalveolar lavage", "Bronchoalveolar lavage fluid",
                         "BAL", "BAL fluid", "BALF",
                         "Pulmonary", "Lung tissue"],
}

_TISSUE_IS_DISEASE = {
    "melanoma", "prostate cancer", "nsclc", "colorectal cancer",
    "hepatocellular carcinoma", "crc", "hcc",
    "hodgkin lymphoma", "multiple myeloma",
    "head and neck squamous cell carcinoma",
    "tramp tumor", "npc",
    "breast cancer", "lung cancer", "gastric cancer", "pancreatic cancer",
    "ovarian cancer", "cervical cancer", "bladder cancer",
    "endometrial cancer", "thyroid cancer", "liver cancer",
    "glioblastoma multiforme", "renal cell carcinoma",
}

_INVALID_TISSUES = {
    "tumor", "tissue", "tissues", "stool", "urine",
    "serum, tissue", "tissue, plasma", "not specified",
    "lymphoblastoid cell lines",
    "ect1/e6e7", "vk2/e6e7",
    "cervix foreskin and tonsil organotypic raft",
}


# =====================================================================
# Disease
# =====================================================================

DISEASE_SYNONYMS: dict[str, list[str]] = {
    "Colorectal cancer":            ["CRC", "Colorectal Cancer",
                                     "Colorectal carcinoma"],
    "Ulcerative colitis":           ["Ulcerative Colitis", "UC"],
    "Non-small cell lung cancer":   ["Non-Small-Cell Lung Cancer", "NSCLC",
                                     "Non-small cell lung cancer"],
    "Rheumatoid arthritis":         ["Rheumatoid Arthritis"],
    "Head and neck squamous cell carcinoma": [
        "Head and Neck Squamous Cell Carcinoma", "HNSCC",
        "Head and neck squamous carcinoma",
    ],
    "Chronic obstructive pulmonary disease": ["COPD"],
    "Alcohol use disorder":         ["AUD"],
    "Non-alcoholic fatty liver disease": [
        "NAFLD", "Nonalcoholic fatty liver disease",
    ],
    "Crohn's disease":              ["CD", "Crohn disease"],
    "Acute kidney injury to chronic kidney disease": ["AKI-to-CKD"],
    "Pancreatic ductal adenocarcinoma": [
        "Pancreatic Ductal Adenocarcinoma", "PDAC",
    ],
    "Alzheimer's disease":          [
        "Alzheimer disease", "Alzheimer's Disease",
    ],
    "Parkinson's disease":          ["Parkinson disease"],
    "Hashimoto's thyroiditis":      [
        "Hashimoto thyroiditis", "Hashimoto's Thyroiditis",
    ],
    "Schizophrenia":                ["SCZ"],
    "Amyotrophic lateral sclerosis": ["ALS"],
    "HIV infection":                ["HIV"],
    "Clear cell renal cell carcinoma": [
        "Clear cell renal carcinoma",
        "Renal clear cell carcinoma",
        "Kidney renal clear cell carcinoma",
    ],
    "Triple-negative breast cancer": ["Triple negative breast cancer"],
    "Non-alcoholic steatohepatitis": [
        "Nonalcoholic steatohepatitis", "NASH",
    ],
    "Esophageal squamous cell carcinoma": [
        "Oesophageal squamous cell carcinoma",
    ],
    "Esophageal adenocarcinoma":    ["Oesophageal adenocarcinoma"],
    "T-cell acute lymphoblastic leukemia": [
        "T cell acute lymphoblastic leukemia",
    ],
    "B-cell acute lymphoblastic leukemia": [
        "Acute B cell lymphoblastic leukemia",
    ],
    "Metabolic dysfunction-associated steatohepatitis": ["MASH"],
    "Metabolic dysfunction-associated steatotic liver disease": [
        "Metabolic Dysfunction-Associated Steatotic Liver Disease", "MASLD",
    ],
    "Gastric adenocarcinoma":       ["Stomach adenocarcinoma"],
    "Early-onset preeclampsia":     ["Early-onset pre-eclampsia",
                                     "Early onset preeclampsia",
                                     "Early onset pre-eclampsia"],
    "Late-onset preeclampsia":      ["Late-onset pre-eclampsia",
                                     "Late onset preeclampsia",
                                     "Late onset pre-eclampsia"],
    "Ischemic stroke":              ["Acute Ischemic Stroke",
                                     "Acute ischemic stroke"],
    "Systemic lupus erythematosus": ["Systemic Lupus Erythematosus", "SLE"],
    "Chronic kidney disease":       ["Chronic Kidney Disease", "CKD"],
    "Type 1 diabetes":              ["Type 1 Diabetes", "T1D"],
    "Type 2 diabetes":              ["Type 2 diabetes mellitus", "T2D",
                                     "Type 2 Diabetes"],
    "Multiple sclerosis":           ["Multiple Sclerosis", "MS"],
    "Relapsing-remitting multiple sclerosis": [
        "Relapsing-remitting Multiple Sclerosis",
    ],
    "Myelodysplastic syndrome":     ["Myelodysplastic syndromes",
                                     "Myelodysplastic neoplasms", "MDS"],
    "IgA nephropathy":              ["IgAN"],
    "Hepatocellular carcinoma":     ["HCC",
                                     "Liver hepatocellular carcinoma"],
    "Diffuse large B-cell lymphoma": [
        "Diffuse large B cell lymphoma", "DLBCL",
    ],
    "Preeclampsia":                 ["Pre-eclampsia"],
    "Acute respiratory distress syndrome": ["ARDS"],
    "Acute myeloid leukemia":       ["AML"],
    "Acute lymphoblastic leukemia": ["ALL"],
    "Chronic myeloid leukemia":     ["CML"],
    "Chronic lymphocytic leukemia": ["CLL"],
    "Neuromyelitis optica spectrum disorder": [
        "Neuromyelitis Optica Spectrum Disorder",
    ],
    "Malignant ascites":            ["Malignant Ascites"],
    "Acute lung injury":            ["Acute Lung Injury"],
    "Renal cell carcinoma":         ["Renal cancer"],
    "Coronary artery disease":      ["Coronary heart disease"],
}

_SPELLING_MAP = {
    "oesophageal": "esophageal",
    "leukaemia": "leukemia",
    "tumour": "tumor",
    "behaviour": "behavior",
    "defence": "defense",
    "anaemia": "anemia",
    "haemorrhage": "hemorrhage",
    "foetal": "fetal",
    "colour": "color",
}


# =====================================================================
# 构建反向查找表
# =====================================================================

def _build_lookup(synonyms: dict[str, list[str]]) -> dict[str, str]:
    """从 {canonical: [aliases]} 构建 {alias_lower: canonical}"""
    lookup: dict[str, str] = {}
    for canonical, aliases in synonyms.items():
        lookup[canonical.lower()] = canonical
        for alias in aliases:
            lookup[alias.lower()] = canonical
    return lookup


_cell_type_lookup = _build_lookup(CELL_TYPE_SYNONYMS)
_subtype_lookup   = _build_lookup(SUBTYPE_SYNONYMS)
_tissue_lookup    = _build_lookup(TISSUE_SYNONYMS)
_disease_lookup   = _build_lookup(DISEASE_SYNONYMS)


# =====================================================================
# 单字段标准化函数
# =====================================================================

def _try_cell_suffix(key: str, lookup: dict[str, str]) -> str | None:
    """尝试添加/去除 ' cell' 后缀后在 lookup 中查找。"""
    if key.endswith(" cell"):
        alt = key[:-5].strip()
    else:
        alt = key + " cell"
    if alt in lookup:
        return lookup[alt]
    return None


def _resolve_slash(text: str) -> str:
    """处理斜杠复合类型，取第一个有效部分并补全后缀。
    'stem/progenitor cell' → 'Stem cell'
    'T/NK cell' → 'T cell'
    'Podocyte/Tubular Epithelia' → 'Podocyte'
    """
    if "/" not in text:
        return text
    parts = text.split("/")
    first = parts[0].strip()
    if not first:
        return text

    tail = parts[-1].strip()
    tail_words = tail.split()
    if len(tail_words) > 1 and first[0].islower() and not first.endswith("cell"):
        suffix = " " + tail_words[-1]
        first = first + suffix

    return first


_ARABIC_TO_ROMAN = {"1": "I", "2": "II", "3": "III", "4": "IV", "5": "V"}


def _canonicalize_cell_name(text: str) -> str:
    """统一 positive/negative、阿拉伯/罗马数字、逗号分隔等常见变体。"""
    text = re.sub(r"[\s-]+positive\b,?\s*", "+ ", text)
    text = re.sub(r"[\s-]+negative\b,?\s*", "- ", text)

    def _to_roman(m):
        return "type " + _ARABIC_TO_ROMAN.get(m.group(1), m.group(1))

    text = re.sub(r"\btype\s+(\d)\b", _to_roman, text, flags=re.IGNORECASE)
    return re.sub(r"  +", " ", text).strip()


def _try_dehyphenate(key: str, lookup: dict[str, str]) -> str | None:
    """尝试替换/移除连字符后在 lookup 中查找。"""
    if "-" not in key:
        return None
    alt = re.sub(r"  +", " ", key.replace("-", " ")).strip()
    if alt in lookup:
        return lookup[alt]
    alt2 = key.replace("-", "")
    if alt2 in lookup:
        return lookup[alt2]
    return None


def normalize_cell_type(raw: str) -> str | None:
    """标准化 cell_type 字段，返回 None 表示应丢弃。"""
    if not raw or not raw.strip():
        return None
    text = _normalize_unicode(raw)
    if not text:
        return None

    text = _resolve_slash(text)
    text = _canonicalize_cell_name(text)

    if text.lower() in _INVALID_CELL_TYPES:
        return None

    key = text.lower()
    if key in _cell_type_lookup:
        return _cell_type_lookup[key]

    text = _singularize(text)
    key = text.lower()
    if key in _cell_type_lookup:
        return _cell_type_lookup[key]

    found = _try_cell_suffix(key, _cell_type_lookup)
    if found:
        if found.lower() in _INVALID_CELL_TYPES:
            return None
        return found

    found = _try_dehyphenate(key, _cell_type_lookup)
    if found:
        if found.lower() in _INVALID_CELL_TYPES:
            return None
        return found

    if text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def normalize_subtype(raw: str) -> str | None:
    """标准化 cell_subtype 字段，返回 None 表示为空。"""
    if not raw or not raw.strip():
        return None
    text = _normalize_unicode(raw)
    if not text:
        return None
    text = _resolve_slash(text)
    text = _canonicalize_cell_name(text)
    if text.lower() in _INVALID_SUBTYPES:
        return None
    if re.search(r"\(general\)", text, re.IGNORECASE):
        return None

    key = text.lower()
    if key in _subtype_lookup:
        return _subtype_lookup[key]

    text = _singularize(text)
    key = text.lower()
    if key in _subtype_lookup:
        return _subtype_lookup[key]

    found = _try_cell_suffix(key, _subtype_lookup)
    if found:
        return found

    found = _try_dehyphenate(key, _subtype_lookup)
    if found:
        return found

    if text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def normalize_tissue(raw: str) -> str | None:
    """标准化 tissue 字段。"""
    if not raw or not raw.strip():
        return None
    text = _normalize_unicode(raw)
    if not text:
        return None
    if text.lower() in _INVALID_TISSUES:
        return None
    if text.lower() in _TISSUE_IS_DISEASE:
        return None

    key = text.lower()
    if key in _tissue_lookup:
        return _tissue_lookup[key]

    text = re.sub(r"\s+tissues?$", "", text, flags=re.IGNORECASE).strip()
    if not text:
        return None
    if text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def _apply_spelling_map(text: str) -> str:
    """英式 → 美式拼写。"""
    low = text.lower()
    for brit, amer in _SPELLING_MAP.items():
        if brit in low:
            pattern = re.compile(re.escape(brit), re.IGNORECASE)
            text = pattern.sub(amer, text)
            low = text.lower()
    return text


def normalize_disease(raw: str) -> str | None:
    """标准化 disease 字段。"""
    if not raw or not raw.strip():
        return None
    text = _normalize_unicode(raw)
    if not text:
        return None

    if text.lower() == "normal":
        return "Normal"
    if text.lower() in ("not specified", "n/a", "null", "none"):
        return "Normal"

    text = _apply_spelling_map(text)

    key = text.lower()
    if key in _disease_lookup:
        return _disease_lookup[key]

    text = _singularize_disease(text)
    key = text.lower()
    if key in _disease_lookup:
        return _disease_lookup[key]

    if text[0].islower():
        text = text[0].upper() + text[1:]
    return text


# =====================================================================
# 批量处理
# =====================================================================

_INVALID_MARKERS = {
    "unknown", "null", "none", "na", "n/a",
    "not specified", "not identified", "unspecified",
}

_MAX_MARKER_LEN = 30


_PARENT_SUFFIXES = [
    (" natural killer cell", "NK cell"),
    (" endothelial cell",    "Endothelial cell"),
    (" epithelial cell",     "Epithelial cell"),
    (" dendritic cell",      "Dendritic cell"),
    (" t lymphocyte",        "T cell"),
    (" b lymphocyte",        "B cell"),
    (" macrophage",          "Macrophage"),
    (" neutrophil",          "Neutrophil"),
    (" fibroblast",          "Fibroblast"),
    (" astrocyte",           "Astrocyte"),
    (" monocyte",            "Monocyte"),
    (" nk cell",             "NK cell"),
    (" t cell",              "T cell"),
    (" b cell",              "B cell"),
    (" neuron",              "Neuron"),
]


def _demote_subtype_celltype(
    ct: str, st: str | None,
) -> tuple[str, str | None]:
    """若 cell_type 实际上是某个大类的亚型（如 CD8+ T cell），则：
    - cell_type → 对应大类（T cell）
    - cell_subtype → 原 cell_type（CD8+ T cell），若 subtype 已有值则保留原值。
    """
    ct_lower = ct.lower()
    for suffix, parent in _PARENT_SUFFIXES:
        if ct_lower.endswith(suffix) and ct_lower != parent.lower():
            if st is None:
                st = ct
            return parent, st
    return ct, st


def normalize_marker(raw: str) -> str | None:
    """验证 marker 字段：过滤非法基因符号（含空格的句子、过长文本等）。"""
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    if text.lower() in _INVALID_MARKERS:
        return None
    if " " in text:
        return None
    if len(text) > _MAX_MARKER_LEN:
        return None
    return text


def normalize_markers(markers: list[dict]) -> list[dict]:
    """对一组 marker 条目做全字段标准化，过滤无效条目。"""
    cleaned: list[dict] = []
    for m in markers:
        ct = normalize_cell_type(m.get("cell_type"))
        if ct is None:
            continue

        mk = normalize_marker(m.get("marker"))
        if mk is None:
            continue

        st = normalize_subtype(m.get("cell_subtype"))
        ct, st = _demote_subtype_celltype(ct, st)

        cleaned.append({
            "cell_type":    ct,
            "cell_subtype": st,
            "marker":       mk,
            "tissue":       normalize_tissue(m.get("tissue")) or "Not specified",
            "disease":      normalize_disease(m.get("disease")) or "Normal",
        })
    return cleaned


class DataNormalizer:
    """对 data/extracted/ 下的 JSON 文件进行后处理标准化。"""

    def __init__(self):
        ensure_dirs()

    def process_all(self) -> int:
        json_files = sorted(EXTRACTED_DIR.glob("PMC*.json"))
        if not json_files:
            logger.warning("No extracted files in %s", EXTRACTED_DIR)
            return 0

        total_before = 0
        total_after = 0
        modified = 0

        for fp in json_files:
            data = json.loads(fp.read_text("utf-8"))
            raw_markers = data.get("markers", [])
            total_before += len(raw_markers)

            normalized = normalize_markers(raw_markers)
            total_after += len(normalized)

            if normalized != raw_markers:
                data["markers"] = normalized
                data["valid_marker_count"] = len(normalized)
                fp.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                modified += 1

        dropped = total_before - total_after
        logger.info(
            "Normalization done — %d files modified | %d markers kept | %d dropped",
            modified, total_after, dropped,
        )
        return modified

    # -----------------------------------------------------------------
    # Phase 2: 跨文件层级分析 — 修复 cell_type == cell_subtype
    # -----------------------------------------------------------------

    def resolve_type_subtype_duplicates(self) -> int:
        """基于已有数据构建 cell_type ↔ cell_subtype 层级关系，
        修复 cell_type == cell_subtype 的条目。

        策略（优先级从高到低）:
        1. 若该值在数据中作为某个 cell_type 的下级出现过（有自己的子类型），
           说明它本身就是一个有效的 cell_type → 置 cell_subtype 为 null。
        2. 若该值仅作为其他 cell_type 的 subtype 出现过，从未拥有自己的子类型，
           说明它实际上是 subtype → 将 cell_type 改为最常见的父类。
        3. 若两者皆非（完全无层级信息），视为独立 cell_type → 置 subtype 为 null。
        """
        json_files = sorted(EXTRACTED_DIR.glob("PMC*.json"))
        if not json_files:
            return 0

        parent_children: dict[str, Counter] = defaultdict(Counter)
        child_parents: dict[str, Counter] = defaultdict(Counter)

        for fp in json_files:
            data = json.loads(fp.read_text("utf-8"))
            for m in data.get("markers", []):
                ct = m.get("cell_type", "")
                st = m.get("cell_subtype")
                if ct and st and ct != st:
                    parent_children[ct][st] += 1
                    child_parents[st][ct] += 1

        modified_files = 0
        fixed_entries = 0

        for fp in json_files:
            data = json.loads(fp.read_text("utf-8"))
            markers = data.get("markers", [])
            file_changed = False

            for m in markers:
                ct = m.get("cell_type", "")
                st = m.get("cell_subtype")
                if not (ct and st and ct == st):
                    continue

                if ct in parent_children:
                    m["cell_subtype"] = None
                elif ct in child_parents:
                    best_parent = child_parents[ct].most_common(1)[0][0]
                    m["cell_type"] = best_parent
                else:
                    m["cell_subtype"] = None

                file_changed = True
                fixed_entries += 1

            if file_changed:
                fp.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                modified_files += 1

        logger.info(
            "Type-subtype dedup — %d files modified | %d entries fixed "
            "(hierarchy: %d parents, %d subtypes)",
            modified_files, fixed_entries,
            len(parent_children), len(child_parents),
        )
        return fixed_entries
