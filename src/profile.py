"""一键数据体检：把一份陌生 CSV 摸底摸清楚。

用法：
    python -m src.profile data/raw/xxx.csv
    python -m src.profile data/raw/xxx.csv --figures --top 12
    python -m src.profile data/raw/xxx.csv --rows 50000   # 大文件只抽样

输出：
    终端摘要 + reports/profile_<文件名>.md（含列清单、分布、质量问题清单）
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from .io_utils import load_csv, to_markdown_table

if hasattr(sys.stdout, "reconfigure"):  # Windows 终端中文输出保护
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATE_KEYWORDS = ("date", "time", "日期", "时间", "月份", "年份", "年月")
ID_KEYWORDS = ("id", "编号", "编码", "订单号", "单号", "工号", "手机", "电话", "账号")
NUMERIC_LIKE_THRESHOLD = 0.9


# ---------------- 列级诊断 ----------------

def _looks_like_date(s: pd.Series) -> bool:
    if not (s.dtype == "object" or str(s.dtype).startswith("str")):
        return False
    sample = s.dropna().astype(str).head(200)
    if sample.empty:
        return False
    parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    return parsed.notna().mean() >= NUMERIC_LIKE_THRESHOLD


def _looks_like_number(s: pd.Series) -> bool:
    if not (s.dtype == "object" or str(s.dtype).startswith("str")):
        return False
    sample = s.dropna().astype(str).str.replace(",", "", regex=False).str.strip().head(500)
    if sample.empty:
        return False
    return pd.to_numeric(sample, errors="coerce").notna().mean() >= NUMERIC_LIKE_THRESHOLD


def column_overview(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    n = len(df)
    for col in df.columns:
        s = df[col]
        nn = int(s.notna().sum())
        nunique = int(s.nunique(dropna=True))
        sample_val = s.dropna().iloc[0] if nn else ""
        sample_txt = str(sample_val)[:32]
        rows.append({
            "列名": col,
            "类型": str(s.dtype),
            "非空": nn,
            "缺失率%": round((n - nn) / n * 100, 1) if n else 0.0,
            "唯一值": nunique,
            "示例": sample_txt,
        })
    return pd.DataFrame(rows)


# ---------------- 质量问题识别 ----------------

def detect_issues(df: pd.DataFrame) -> list[dict]:
    issues: list[dict] = []
    n = len(df)

    dup = int(df.duplicated().sum())
    if dup:
        issues.append({"级别": "高", "类型": "重复行", "说明": f"整行完全重复 {dup} 行（占 {dup / n:.1%}）"})

    for col in df.columns:
        s = df[col]
        miss = s.isna().mean()
        nunique = s.nunique(dropna=True)

        if miss > 0.3:
            issues.append({"级别": "中", "类型": "缺失偏多", "说明": f"`{col}` 缺失率 {miss:.1%}"})
        if nunique == 0:
            issues.append({"级别": "低", "类型": "全空列", "说明": f"`{col}` 全部为空"})
        elif nunique == 1:
            issues.append({"级别": "低", "类型": "常量列", "说明": f"`{col}` 只有一个取值 `{s.dropna().iloc[0]!s:.20}`，无信息量"})
        if nunique == n and n > 10 and any(k in str(col).lower() for k in ID_KEYWORDS):
            issues.append({"级别": "低", "类型": "疑似主键", "说明": f"`{col}` 取值全唯一，可能是一行一个 ID"})
        if _looks_like_number(s) and not _looks_like_date(s):
            issues.append({"级别": "中", "类型": "数值存成文本", "说明": f"`{col}` 看起来是数字但类型为 {s.dtype}，参与计算前需转换"})
        if _looks_like_date(s):
            issues.append({"级别": "中", "类型": "日期存成文本", "说明": f"`{col}` 看起来是日期但类型为 {s.dtype}，建议 pd.to_datetime"})
        if not str(col).isidentifier():
            issues.append({"级别": "低", "类型": "列名不规范", "说明": f"`{col}` 含空格/符号，代码里引用不方便"})

    return issues


# ---------------- 报告 ----------------

def build_report(df: pd.DataFrame, path: Path, top: int = 8) -> str:
    n, m = df.shape
    mem_mb = df.memory_usage(deep=True).sum() / 1024**2
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# 数据体检报告：{path.name}",
        "",
        f"- 生成时间：{now}",
        f"- 规模：**{n:,} 行 × {m} 列**，内存约 {mem_mb:.2f} MB",
        f"- 重复行：{int(df.duplicated().sum()):,}",
        "",
        "## 一、列清单",
        "",
        to_markdown_table(column_overview(df)),
        "",
    ]

    # 质量问题
    issues = detect_issues(df)
    lines += ["## 二、质量问题清单", ""]
    if issues:
        order = {"高": 0, "中": 1, "低": 2}
        issues.sort(key=lambda x: order.get(x["级别"], 3))
        lines.append(to_markdown_table(pd.DataFrame(issues)))
    else:
        lines.append("_(未发现明显问题)_")
    lines.append("")

    # 数值列
    num = df.select_dtypes("number")
    lines += ["## 三、数值列描述", ""]
    if num.shape[1]:
        desc = num.describe().T[["count", "mean", "std", "min", "50%", "max"]]
        desc.columns = ["非空数", "均值", "标准差", "最小", "中位数", "最大"]
        desc.index.name = "列名"
        lines.append(to_markdown_table(desc.round(3), index=True))
    else:
        lines.append("_(无数值列)_")
    lines.append("")

    # 类别列 Top 值
    cat_cols = [c for c in df.columns if df[c].nunique(dropna=True) <= max(50, int(n * 0.05))
                and not pd.api.types.is_float_dtype(df[c])]
    lines += ["## 四、类别列取值分布", ""]
    if cat_cols:
        for col in cat_cols[:6]:
            vc = df[col].value_counts(dropna=False).head(top)
            tbl = pd.DataFrame({"取值": [str(i) for i in vc.index], "数量": vc.values})
            tbl["占比%"] = (tbl["数量"] / n * 100).round(1)
            lines += [f"**{col}**（唯一值 {df[col].nunique():,}）", "", to_markdown_table(tbl), ""]
    else:
        lines += ["_(无低基数类别列)_", ""]

    # 相关性
    lines += ["## 五、数值列相关性（|r| 最强的前 10 对）", ""]
    if num.shape[1] >= 2:
        corr = num.corr(numeric_only=True)
        # 手工构造成对列表，避免依赖 numpy
        rows: list[dict] = []
        cols = list(corr.columns)
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                r = corr.loc[a, b]
                if pd.notna(r):
                    rows.append({"列 A": a, "列 B": b, "相关系数": round(float(r), 3), "|r|": abs(float(r))})
        rows.sort(key=lambda x: x["|r|"], reverse=True)
        pairs_tbl = pd.DataFrame(rows[:10]).drop(columns=["|r|"]) if rows else pd.DataFrame()
        lines.append(to_markdown_table(pairs_tbl) if not pairs_tbl.empty else "_(无有效数值对)_")
    else:
        lines.append("_(数值列不足 2 个)_")
    lines.append("")

    return "\n".join(lines)


def terminal_summary(df: pd.DataFrame, path: Path) -> None:
    print("=" * 66)
    print(f"数据体检：{path.name}")
    print("=" * 66)
    print(f"规模        : {len(df):,} 行 × {df.shape[1]} 列")
    print(f"内存        : {df.memory_usage(deep=True).sum() / 1024**2:.2f} MB")
    print(f"重复行      : {int(df.duplicated().sum()):,}")
    print(f"完全空列    : {sum(df[c].isna().all() for c in df.columns)}")

    num = df.select_dtypes("number").columns.tolist()
    cat = [c for c in df.columns if c not in num]
    print(f"数值列({len(num)}) : {', '.join(map(str, num[:8]))}{' ...' if len(num) > 8 else ''}")
    print(f"非数值列({len(cat)}): {', '.join(map(str, cat[:8]))}{' ...' if len(cat) > 8 else ''}")

    miss = (df.isna().mean() * 100).sort_values(ascending=False)
    miss = miss[miss > 0].head(5)
    if not miss.empty:
        print("缺失最多    : " + "  ".join(f"{c}={v:.1f}%" for c, v in miss.items()))

    issues = detect_issues(df)
    print(f"问题条目    : {len(issues)} 条")
    for it in issues[:6]:
        print(f"  [{it['级别']}] {it['类型']}: {it['说明']}")
    print("=" * 66)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CSV 数据体检")
    ap.add_argument("csv", help="CSV 文件路径")
    ap.add_argument("--rows", type=int, default=None, help="只读取前 N 行（大文件抽样）")
    ap.add_argument("--encoding", default=None, help="指定编码，默认自动探测")
    ap.add_argument("--sep", default=None, help="指定分隔符，默认自动探测")
    ap.add_argument("--top", type=int, default=8, help="类别列展示前 N 个取值")
    ap.add_argument("--figures", action="store_true", help="同时生成图表到 reports/figures/")
    ap.add_argument("--out", default=None, help="报告输出路径")
    args = ap.parse_args(argv)

    path = Path(args.csv)
    df = load_csv(path, encoding=args.encoding, sep=args.sep, nrows=args.rows)

    terminal_summary(df, path)

    report = build_report(df, path, top=args.top)
    out = Path(args.out) if args.out else Path("reports") / f"profile_{path.stem}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"报告已写入  : {out}")

    if args.figures:
        from . import plotting as P

        font = P.setup_style()
        print(f"绘图中文字体: {font}")
        num_cols = df.select_dtypes("number").columns.tolist()
        if num_cols:
            fig, _ = P.hist_grid(df, num_cols[:6])
            print("  直方图    ->", P.save_fig(fig, f"{path.stem}_hist"))
        if len(num_cols) >= 2:
            fig, _ = P.corr_heatmap(df)
            print("  相关性图  ->", P.save_fig(fig, f"{path.stem}_corr"))
        cat_cols = [c for c in df.columns if c not in num_cols and df[c].nunique() <= 30]
        for col in cat_cols[:3]:
            fig, _ = P.bar_top(df[col], top=args.top, title=f"{col} 分布")
            print("  分布图    ->", P.save_fig(fig, f"{path.stem}_bar_{col}"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
