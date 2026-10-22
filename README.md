# code_mission

关灯科技 · 实战任务仓库。

> **业务目标**：_待补充_
> **数据来源**：`data/raw/` 下的一份 CSV

---

## 一、环境

| 项 | 值 |
|---|---|
| Python | 3.13（虚拟环境 `~/.workbuddy/binaries/python/envs/default`）|
| 核心库 | pandas · numpy · scipy · pyarrow · matplotlib · seaborn · openpyxl · duckdb |
| 交互环境 | JupyterLab（kernel 名 `code-mission`）|

安装 / 补齐依赖：

```bash
pip install -i https://pypi.org/simple -r requirements.txt
```

> 本机 pip 默认源不可用，务必带 `-i https://pypi.org/simple`。

---

## 二、目录结构

```
code_mission/
├── data/
│   ├── raw/          # 原始 CSV（只读，不做二次修改）
│   ├── interim/      # 清洗后的中间态
│   └── processed/    # 分析用结果表
├── notebooks/        # 探索性分析（EDA）
├── src/
│   ├── io_utils.py   # 健壮读 CSV：自动探测编码 / 分隔符
│   ├── plotting.py   # 中文图表样式（解决方块字、负号）
│   └── profile.py    # 一键数据体检，输出 Markdown 报告
├── reports/
│   ├── figures/      # 图表
│   └── profile_*.md  # 体检报告
└── requirements.txt
```

---

## 三、快速开始

```bash
# 1. 把 CSV 放进 data/raw/，例如 data/raw/orders.csv

# 2. 先体检，摸清字段、缺失、异常
python -m src.profile data/raw/orders.csv

# 3. 需要图表就加 --figures（图存到 reports/figures/）
python -m src.profile data/raw/orders.csv --figures --top 12

# 4. 大文件先抽样
python -m src.profile data/raw/big.csv --rows 50000

# 5. 打开 notebook 做深入分析
jupyter lab
```

体检报告输出到 `reports/profile_<文件名>.md`，包含：列清单、质量问题清单（重复行 / 缺失 / 常量列 / 数值存成文本 / 日期存成文本）、数值列描述、类别分布、相关性 Top10。

---

## 四、代码里怎么用

```python
from src.io_utils import load_csv
from src import plotting as P

df = load_csv("data/raw/orders.csv")   # 编码、分隔符自动探测
P.setup_style()                        # 中文不乱码，负号正常

fig, ax = P.bar_top(df["城市"], top=10)
P.save_fig(fig, "city_dist")
```

常用图函数：

- `P.bar_top(series, top=10)` —— 类别分布
- `P.hist_grid(df, cols=None)` —— 多列直方图
- `P.corr_heatmap(df, method="pearson")` —— 相关性热力图
- `P.save_fig(fig, "名字")` —— 保存到 `reports/figures/`

---

## 五、约定

- `data/raw/` 与中间产物默认**不入库**（见 `.gitignore`），避免仓库被大文件撑爆。若那份 CSV 体积小、希望随仓库发布，用 `git add -f data/raw/xxx.csv` 强制加入。
- 分析脚本放 `src/`，探索性内容放 `notebooks/`，结论放 `reports/`。
- 提交信息一句话说清做了什么，例如 `feat: 增加数据体检脚本`。
