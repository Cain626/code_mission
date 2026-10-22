# code_mission

关灯科技 · 实战任务仓库。

> **业务目标**：减少业务分析师因大模型生成的 SQL 执行报错而损失的等待与排查时间
> **数据**：`data/sql_queries.csv`（2026-09-01 ~ 09-07，1025 行原始 / 976 条去重查询）
> **当前进度**：问题定位已完成，见 [`reports/问题定位分析.md`](reports/问题定位分析.md)

---

## 一、仓库构成

| 部分 | 目录 | 说明 |
|---|---|---|
| 问题定位分析 | `src/` `reports/` `data/` `notebooks/` | 对 `sql_queries.csv` 的诊断脚本、图表与结论 |
| 问穹系统 · 后端 | `data-lx-agent/` | FastAPI + LangGraph，NL2SQL 智能体，SSE 流式返回 |
| 问穹系统 · 前端 | `date-lx-agent-frontend/` | Vue 3 + Vite，对话式问数界面 |

后端的智能体是一条 LangGraph 流程图，节点都在 `data-lx-agent/app/agent/nodes/`：
`extract_keywords → recall_table / recall_column / recall_metric / recall_value → filter_table / filter_metric → generate_sql → validate_sql → execute_sql → correct_sql`。

---

## 二、问穹系统：怎么跑起来

### 1. 起依赖服务（Docker）

```bash
cd data-lx-agent/docker
docker compose up -d      # mysql 3306 · elasticsearch 9200 · kibana 5601 · qdrant 6333 · embedding 8081
```

首次启动 MySQL 会自动导入 `docker/mysql/` 下的 `dw.sql`（数仓 `dw`）与 `meta.sql`（元数据库 `meta`）。

> **embedding 模型权重没有入库**（`docker/embedding/bge-large-zh-v1.5` 约 1.3G）。
> 需要先把 `BAAI/bge-large-zh-v1.5` 放到 `data-lx-agent/docker/embedding/bge-large-zh-v1.5`，
> 否则 embedding 容器起不来、向量召回会失败。

### 2. 配置

```bash
cd data-lx-agent
cp conf/app_config.example.yaml conf/app_config.yaml   # 然后填自己的 DeepSeek API Key
```

`conf/app_config.yaml` 已被 `.gitignore` 排除，**不要提交真实 Key**。

### 3. 起后端（8000）

```bash
cd data-lx-agent
uv sync                  # 依赖见 pyproject.toml / uv.lock
uv run fastapi dev main.py
```

接口只有一个：`POST /api/query`，body `{"query": "..."}`，返回 SSE 流（含检索、生成、执行各步骤）。

### 4. 起前端（8080）

```bash
cd date-lx-agent-frontend
npm install
npm run dev              # http://localhost:8080 ，/api 已代理到 8000
```

---

## 三、分析环境

| 项 | 值 |
|---|---|
| Python | 3.13（虚拟环境 `~/.workbuddy/binaries/python/envs/default`）|
| 核心库 | pandas · numpy · scipy · pyarrow · matplotlib · seaborn · openpyxl · duckdb |
| 交互环境 | JupyterLab（kernel 名 `code-mission`）|

补齐依赖：

```bash
pip install -i https://pypi.org/simple -r requirements.txt
```

> 本机 pip 默认源不可用，务必带 `-i https://pypi.org/simple`。
> 注意：这是**分析侧**的环境；后端 `data-lx-agent` 用自己的 `uv` 环境和 `pyproject.toml`，两者互不干扰。

---

## 四、目录结构

```
code_mission/
├── data/
│   ├── sql_queries.csv   # 任务数据
│   ├── raw/ interim/ processed/
├── data-lx-agent/            # 后端：FastAPI + LangGraph 问数智能体
│   ├── app/
│   │   ├── agent/            # LangGraph 图、节点、状态
│   │   ├── api/              # 路由 / 依赖 / schema
│   │   ├── clients/          # mysql · es · qdrant · embedding 客户端
│   │   ├── repositories/     # 各存储的读写封装
│   │   ├── services/         # 业务服务
│   │   └── conf/ core/ models/ prompts/
│   ├── conf/
│   │   ├── app_config.example.yaml   # 配置样例（照抄成 app_config.yaml）
│   │   └── meta_config.yaml          # 表 / 字段 / 指标元数据定义
│   ├── docker/               # compose + 建库 SQL + ES IK 插件
│   ├── main.py  pyproject.toml  uv.lock
├── date-lx-agent-frontend/   # 前端：Vue 3 + Vite
│   ├── src/  public/  index.html  vite.config.js
├── notebooks/                # 探索性分析（EDA）
├── src/                      # 分析脚本
│   ├── io_utils.py           # 健壮读 CSV：自动探测编码 / 分隔符
│   ├── plotting.py           # 中文图表样式（解决方块字、负号）
│   ├── profile.py            # 一键数据体检，输出 Markdown 报告
│   └── analyze_queries.py  dig_queries*.py  make_figures.py   # 本次问题定位
├── reports/                  # 分析结论与图表
└── requirements.txt
```

---

## 五、分析侧快速开始

```bash
# 1. 数据体检，摸清字段、缺失、异常
python -m src.profile data/sql_queries.csv --figures

# 2. 复现问题定位的六阶段分析
python -m src.analyze_queries
python -m src.dig_queries2   # 3/4/5 同理
python -m src.make_figures

# 3. 打开 notebook
jupyter lab
```

代码里怎么用：

```python
from src.io_utils import load_csv
from src import plotting as P

df = load_csv("data/sql_queries.csv")   # 编码、分隔符自动探测
P.setup_style()                         # 中文不乱码，负号正常
fig, ax = P.bar_top(df["data_domain"], top=10)
P.save_fig(fig, "domain_dist")
```

---

## 六、约定

- `data/raw/`、`data-lx-agent/conf/app_config.yaml`、`node_modules/`、`docker/embedding/` 与各类中间产物默认**不入库**。
- 分析脚本放 `src/`，探索性内容放 `notebooks/`，结论放 `reports/`。
- 提交信息一句话说清做了什么，例如 `feat: 增加数据体检脚本`。
