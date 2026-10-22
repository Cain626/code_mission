"""sql_queries.csv 问题定位分析（第一阶段：只做诊断，不给方案）。

运行：
    python -m src.analyze_queries
输出：终端分段报表，便于逐段判断问题在哪。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .io_utils import load_csv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CSV = Path("data/sql_queries.csv")
LOSS_PER_FAIL_MIN = 75


def title(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def load() -> pd.DataFrame:
    df = load_csv(CSV, verbose=False)
    n0 = len(df)

    # 1) 去掉完全重复的记录（同一 query_id 原样出现多次）
    df = df.drop_duplicates().copy()
    print(f"[清洗] 原始 {n0} 行 -> 去重后 {len(df)} 行（丢弃 {n0 - len(df)} 行完全重复）")

    # 2) 时间统一到同一时区：query_time 带 +08:00，schema_synced_at 是 UTC
    df["query_time"] = pd.to_datetime(df["query_time"], utc=True).dt.tz_convert("Asia/Shanghai")
    df["schema_synced_at"] = pd.to_datetime(df["schema_synced_at"], utc=True).dt.tz_convert("Asia/Shanghai")

    # 3) 元数据快照滞后（小时）
    df["schema_lag_h"] = (df["query_time"] - df["schema_synced_at"]).dt.total_seconds() / 3600

    # 4) 结果状态
    df["status"] = np.where(df.exec_success == 1, "成功",
                     np.where(df.exec_success == 0, "报错", "中断/未回传"))
    df["is_fail"] = (df.exec_success == 0).astype(float)
    return df


def sec_overview(df: pd.DataFrame) -> None:
    title("0. 数据基本面")
    print(f"查询条数（去重后）: {len(df):,}")
    print(f"时间范围          : {df.query_time.min():%Y-%m-%d %H:%M} ~ {df.query_time.max():%Y-%m-%d %H:%M}"
          f"（{(df.query_time.max() - df.query_time.min()).days} 天）")
    print(f"业务部门          : {df.business_unit.nunique()} 个 -> {sorted(df.business_unit.unique())}")
    print(f"数据主题域        : {df.data_domain.nunique()} 个 -> {sorted(df.data_domain.unique())}")
    print(f"重复 query_id     : {int(df.query_id.duplicated().sum())} 条")

    vc = df.status.value_counts()
    print("\n执行结果分布：")
    for k, v in vc.items():
        print(f"  {k:8s} {v:5d}  {v / len(df):6.1%}")
    known = df[df.exec_success.notna()]
    print(f"\n报错率（分母=有结果的 {len(known)} 条）: {df.is_fail.sum():.0f} / {len(known)} = "
          f"{df.is_fail.sum() / len(known):.2%}")
    print(f"报错率（分母=全部 {len(df)} 条，把中断算不失败）: {df.is_fail.sum() / len(df):.2%}")

    print(f"\n元数据快照滞后（小时）: min={df.schema_lag_h.min():.1f}  "
          f"中位={df.schema_lag_h.median():.1f}  mean={df.schema_lag_h.mean():.1f}  "
          f"max={df.schema_lag_h.max():.1f}")
    print(f"置信分: min={df.confidence_score.min()} 中位={df.confidence_score.median()} "
          f"max={df.confidence_score.max()}")
    print(f"提示词长度: min={df.prompt_length.min()} 中位={df.prompt_length.median()} "
          f"max={df.prompt_length.max()}")


def sec_metric_vs_fail(df: pd.DataFrame, col: str, bins, labels=None, name: str = "") -> None:
    known = df[df.exec_success.notna()].copy()
    known["b"] = pd.cut(known[col], bins=bins, labels=labels, include_lowest=True)
    g = known.groupby("b", observed=True).agg(
        查询数=("is_fail", "size"), 报错数=("is_fail", "sum"), 报错率=("is_fail", "mean"))
    g["报错率"] = (g["报错率"] * 100).round(1)
    print(f"\n-- {name} × 报错率 --")
    print(g.to_string())

    # 成功 vs 报错的分布差异
    a = df[df.exec_success == 1][col].dropna()
    b = df[df.exec_success == 0][col].dropna()
    print(f"   成功组 {col}: 中位={a.median():.1f} 均值={a.mean():.1f} | "
          f"报错组: 中位={b.median():.1f} 均值={b.mean():.1f}")


def sec_time(df: pd.DataFrame) -> None:
    title("1. 时间维度：报错是否在某个时间段集中爆发")
    d = df.set_index("query_time").sort_index()
    daily = d.resample("D").agg(查询数=("exec_success", "size"),
                                报错数=("is_fail", "sum"),
                                中断数=("exec_success", lambda s: s.isna().sum()))
    daily["报错率%"] = (daily["报错数"] / (daily["查询数"] - daily["中断数"]) * 100).round(1)
    daily["快照滞后h_中位"] = d["schema_lag_h"].resample("D").median().round(1)
    print(daily.to_string())

    hourly = d.groupby(d.index.hour).agg(查询数=("exec_success", "size"), 报错率=("is_fail", "mean"))
    hourly["报错率%"] = (hourly["报错率"] * 100).round(1)
    print("\n-- 按发起小时 --")
    print(hourly[["查询数", "报错率%"]].T.to_string())


def sec_entity(df: pd.DataFrame, col: str, name: str) -> pd.DataFrame:
    known = df[df.exec_success.notna()]
    g = known.groupby(col).agg(查询数=("is_fail", "size"), 报错数=("is_fail", "sum"),
                               报错率=("is_fail", "mean"),
                               置信分中位=("confidence_score", "median"),
                               快照滞后h中位=("schema_lag_h", "median"),
                               提示词中位=("prompt_length", "median"))
    g["报错率"] = (g["报错率"] * 100).round(1)
    g = g.sort_values("报错数", ascending=False)
    g["报错占比"] = (g["报错数"] / g["报错数"].sum() * 100).round(1)
    print(f"\n-- 按{name}（按报错数降序）--")
    print(g.to_string())
    return g


def sec_combo(df: pd.DataFrame) -> None:
    title("4. 部门 × 主题域：失败是否集中在少数组合")
    known = df[df.exec_success.notna()]
    g = known.groupby(["business_unit", "data_domain"]).agg(
        查询数=("is_fail", "size"), 报错数=("is_fail", "sum"), 报错率=("is_fail", "mean"))
    g["报错率"] = (g["报错率"] * 100).round(1)
    g = g.sort_values("报错数", ascending=False)
    print(g.head(15).to_string())
    tot = g["报错数"].sum()
    print(f"\n前 5 个组合贡献报错: {g['报错数'].head(5).sum()}/{tot} = "
          f"{g['报错数'].head(5).sum() / tot:.1%}")
    print(f"组合数: {len(g)}，其中有报错的组合: {(g['报错数'] > 0).sum()}")


def sec_interaction(df: pd.DataFrame) -> None:
    title("5. 叠加效应：低置信 × 长提示词 × 快照滞后")
    known = df[df.exec_success.notna()].copy()
    known["低置信"] = known.confidence_score <= 10
    known["长提示"] = known.prompt_length > known.prompt_length.median()
    known["滞后久"] = known.schema_lag_h > 24

    for a, b in [("低置信", "长提示"), ("低置信", "滞后久")]:
        t = known.groupby([a, b]).agg(n=("is_fail", "size"), fail=("is_fail", "sum"),
                                      rate=("is_fail", "mean"))
        t["rate"] = (t["rate"] * 100).round(1)
        print(f"\n-- {a} × {b} --")
        print(t.to_string())


def sec_null(df: pd.DataFrame) -> None:
    title("6. 中断/未回传（exec_success 为空）是什么画像")
    known = df[df.exec_success.notna()]
    nulls = df[df.exec_success.isna()]
    print(f"中断条数: {len(nulls)}")
    for col in ["business_unit", "data_domain"]:
        cmp = pd.DataFrame({
            "中断组占比%": (nulls[col].value_counts(normalize=True) * 100).round(1),
            "正常组占比%": (known[col].value_counts(normalize=True) * 100).round(1),
        }).fillna(0)
        cmp["差额"] = (cmp["中断组占比%"] - cmp["正常组占比%"]).round(1)
        print(f"\n-- {col} --")
        print(cmp.sort_values("差额", key=abs, ascending=False).to_string())

    for col in ["confidence_score", "prompt_length", "schema_lag_h"]:
        print(f"{col:16s} 中断组 中位={nulls[col].median():.1f} / 正常组 中位={known[col].median():.1f}")
    print(f"中断发生小时: {sorted(nulls.query_time.dt.hour.unique().tolist())}")
    print(f"中断按天: {nulls.query_time.dt.date.value_counts().sort_index().to_dict()}")


def sec_loss(df: pd.DataFrame) -> None:
    title("7. 损失量化（口径：单次报错 75 分钟）")
    fails = int(df.is_fail.sum())
    print(f"报错次数 {fails} × 75 分钟 = {fails * LOSS_PER_FAIL_MIN / 60:.1f} 小时 "
          f"≈ {fails * LOSS_PER_FAIL_MIN / 60 / 8:.1f} 人日")
    known = df[df.exec_success.notna()]
    g = known.groupby("data_domain")["is_fail"].agg(["sum", "size"])
    g["损失h"] = g["sum"] * LOSS_PER_FAIL_MIN / 60
    print("\n-- 按主题域分摊 --")
    print(g.sort_values("损失h", ascending=False).round(1).to_string())


def main() -> None:
    df = load()
    sec_overview(df)
    sec_time(df)
    title("2. 元数据快照滞后 × 报错率")
    sec_metric_vs_fail(df, "schema_lag_h",
                       bins=[-0.01, 1, 3, 6, 12, 24, 48, 1e9],
                       labels=["<1h", "1-3h", "3-6h", "6-12h", "12-24h", "24-48h", ">48h"],
                       name="快照滞后")
    title("3. 置信分 / 提示词长度 × 报错率")
    sec_metric_vs_fail(df, "confidence_score",
                       bins=[-0.1, 5, 10, 15, 20, 25, 30],
                       labels=["0-5", "6-10", "11-15", "16-20", "21-25", "26-30"],
                       name="置信分")
    sec_metric_vs_fail(df, "prompt_length",
                       bins=[0, 30, 45, 60, 75, 1e9],
                       labels=["<=30", "31-45", "46-60", "61-75", ">75"],
                       name="提示词长度")
    title("3b. 部门 / 主题域 × 报错率")
    sec_entity(df, "business_unit", "业务部门")
    sec_entity(df, "data_domain", "主题域")
    sec_combo(df)
    sec_interaction(df)
    sec_null(df)
    sec_loss(df)


if __name__ == "__main__":
    main()
