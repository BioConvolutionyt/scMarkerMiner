# scMarkerMiner Database

LLM 驱动的单细胞 Marker 基因自动挖掘系统。从 NCBI PMC 文献中批量提取细胞类型 Marker 信息，经多层标准化后入库，提供多维检索与可视化分析。
**在线访问：[https://scmarkerminer.vercel.app](https://scmarkerminer.vercel.app/)**

## 架构

```
PubMed/PMC (7000+ 篇)
    │  E-utilities API
    ▼
┌─ Pipeline ──────────────────────────────────────┐
│  Fetch XML → Parse → LLM Extract → HGNC Fix    │
│           → Normalize → Load DB                 │
└─────────────────────────────────────────────────┘
    │                                    │
    ▼                                    ▼
 MySQL (SQLPub)              Vercel Serverless
    │                         FastAPI + Vue 3
    └──────── 查询 ───────────→  前端界面
```

## 数据流水线

| 阶段 | 模块 | 说明 |
|------|------|------|
| 1 | `pipeline/fetcher.py` | NCBI E-utilities 批量获取 PMC OA 全文 XML（2012+，人类，临床/综述类） |
| 2 | `pipeline/parser.py` | JATS XML 解析，提取 Abstract / Results / Tables，转 Markdown，Token 长度控制 |
| 3 | `pipeline/extractor.py` | GPT-5.4-mini 结构化抽取：Cell Type · Subtype · Marker · Tissue · Disease |
| 4 | `pipeline/validator.py` | HGNC 官方数据校验基因符号，别名修正，无效符号过滤 |
| 5 | `pipeline/normalizer.py` | 多层标准化：同义词合并、连字符/拼写/单复数统一、Cell Type↔Subtype 层级修正 |
| 6 | `pipeline/loader.py` | 写入 MySQL，自动去重，统计引用次数 |

可选阶段：`scripts/run_validation.py` — 使用 GPT-5.4 对抽取结果进行抽样交叉验证。

## 技术栈

| 层 | 技术 |
|----|------|
| 数据挖掘 | Python 3.11 · OpenAI API · lxml · aiohttp |
| 后端 | FastAPI · SQLAlchemy 2.0 · PyMySQL |
| 前端 | Vue 3 · Vite · Element Plus · ECharts |
| 数据库 | MySQL 8.0 (本地) / SQLPub (线上) |
| 部署 | Vercel (前端 CDN + Python Serverless) · GitHub Actions |

## 项目结构

```
scMarkerMiner/
├── config/settings.py            # 全局配置（通过环境变量注入敏感信息）
├── pipeline/                     # 数据挖掘流水线
│   ├── fetcher.py                #   NCBI PMC 文献下载
│   ├── parser.py                 #   XML 解析与文本预处理
│   ├── extractor.py              #   LLM 结构化信息抽取
│   ├── validator.py              #   HGNC 基因符号标准化
│   ├── normalizer.py             #   字段标准化与去重
│   ├── llm_validator.py          #   LLM 交叉验证
│   └── loader.py                 #   数据库批量导入
├── database/
│   ├── models.py                 # SQLAlchemy ORM（7 张表）
│   ├── crud.py                   # get_or_create CRUD
│   └── schema.sql                # DDL 参考
├── api/
│   ├── main.py                   # FastAPI 入口
│   ├── index.py                  # Vercel Serverless 入口
│   ├── schemas.py                # Pydantic 响应模型
│   └── routes/                   # markers · cells · stats · export
├── frontend/
│   ├── src/views/                # Dashboard · Search · MarkerDetail
│   └── public/favicon.svg
├── scripts/
│   ├── run_pipeline.py           # 流水线统一入口
│   └── run_validation.py         # 独立验证脚本
├── vercel.json                   # Vercel 部署配置
├── requirements.txt              # Python 全量依赖
└── .github/workflows/            # GitHub Actions
```


## 流水线配置

通过 `config/settings.py` 或环境变量控制：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `PILOT_MODE` | `False` | 试运行模式（仅处理 PILOT_SIZE 篇） |
| `BATCH_LIMIT` | `0` (环境变量) | 每次运行最大处理量，0 = 不限制 |
| `OPENAI_MODEL` | `openai/gpt-5.4-mini` | 主力抽取模型 |
| `VALIDATION_MODEL` | `openai/gpt-5.4` | 验证模型 |
| `OPENAI_CONCURRENT_LIMIT` | `5` | LLM 并发请求数 |
| `TEXT_MAX_TOKENS` | `10000` | 单篇文本最大 Token |

## 使用说明

### Dashboard（首页）

展示数据库收录概况：

- **统计卡片**：Markers 总数、Cell Types 数、Diseases 数、Tissues 数、文献数、条目数
- **Cell Type 分布**：饼图展示各细胞类型占比
- **Tissue 分布**：横向柱状图展示组织来源分布

### Marker Search（检索页）

多维组合检索，结果按引用次数降序排列：

| 筛选条件 | 说明 |
|----------|------|
| Cell Type | 细胞大类（如 T cell、Macrophage），支持多选 |
| Subtype | 细胞亚型（如 CD8+ T cell、M2 macrophage），支持多选 |
| Tissue | 组织来源（如 Lung、Blood），支持多选 |
| Disease | 疾病类型（如 Colorectal cancer），支持多选 |
| Marker | 基因符号关键词模糊搜索 |

各筛选条件**级联联动**：选定某一条件后，其余下拉选项仅保留有交集的值。

检索结果下方提供**气泡图 + 侧边排行列表**：
- 气泡图以 Cell Type 为颜色维度，气泡大小反映引用次数
- 侧边列表按 Cell Type 分组，展示全部 Marker 及引用次数
- 点击气泡可定位到侧边列表对应条目
- 支持导出为 CSV / XLSX

### Marker Detail（详情页）

点击表格中的 Marker 符号进入详情页，展示：

- 该 Marker 关联的所有 Cell Types、Subtypes、Tissues、Diseases
- 完整条目列表（含来源文献 PMID、验证状态），支持分页浏览

## License

MIT
