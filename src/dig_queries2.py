"""第三阶段：排除干扰项，找真正可解释的残余部分。

前面已确认：
  - confidence_score 与报错无关（r=-0.02, p=0.55），是干扰项
  - 时段、主题域与报错无关（卡方不显著）
  - 快照滞后 >1h 是最强单因子（54% 报错），但只覆盖 19% 的报错
本阶段要回答：
  1) 报错是否成簇出现（同一时间窗内连环报错）→ 指向时段性故障而非单条查询问题
  2) 分天波动（3.3% ~ 17.4%）是随机还是存在「坏日子」
  3) 部门差异（供应链 14.7% vs 零售 4.9%）在控制滞后和提示词后是否仍然存在
  4) 滞后在 1 小时临界点附近的变化形状
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .io_utils import load_csv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def title(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def prep() -> pd.DataFrame:
    df = load_csv(Path("data/sql_queries.csv"), verbose=False).drop_duplicates().copy()
    df["query_time"] = pd.to_datetime(df.query_time, utc=True).dt.tz_convert("Asia/Shanghai")
    df["schema_synced_at"] = pd.to_datetime(df.schema_synced_at, utc=True).dt.tz_convert("Asia/Shanghai")
    df["schema_lag_h"] = (df.query_time - df.schema_synced_at).dt.total_seconds() / 3600
    df["is_fail"] = (df.exec_success == 0).astype(float)
    return df


def clustering(df: pd.DataFrame) -> None:
    title("1. 报错是否成簇：同一条时间轴上连环失败")
    k = df[df.exec_success.notna()].sort_values("query_time").reset_index(drop=True)
    fails = k[k.is_fail == 1]
    gaps = []
    for t in fails.query_time:
        window = k[(k.query_time >= t - pd.Timedelta("10min")) &
                   (k.query_time <= t + pd.Timedelta("10min"))]
        gaps.append(int(window.is_fail.sum()) - 1)
    gaps = np.array(gaps)
    p = k.is_fail.mean()
    # 随机独立假设下，±10 分钟内期望的其他失败数
    win_n = np.mean([len(k[(k.query_time >= t - pd.Timedelta("10min")) &
                           (k.query_time <= t + pd.Timedelta("10min"))]) - 1
                     for t in fails.query_time])
    print(f"报错 {len(fails)} 条，其中 ±10 分钟内还有别的报错的: {(gaps > 0).sum()} 条 "
          f"({(gaps > 0).mean():.1%})")
    print(f"每条报错在 ±10 分钟窗口内平均还有其他报错 {gaps.mean():.2f} 条；"
          f"随机独立假设下期望 {win_n * p:.2f} 条")
    print(f"→ 观测/期望 = {gaps.mean() / (win_n * p):.2f} 倍")

    print("\n按 30 分钟粒度看报错分布（Top10 最集中的时间桶）：")
    bucket = k.set_index("query_time").is_fail.resample("30min").agg(["size", "sum"])
    bucket.columns = ["查询数", "报错数"]
    bucket = bucket[bucket["报错数"] > 0].sort_values("报错数", ascending=False)
    bucket["报错率%"] = (bucket["报错数"] / bucket["查询数"] * 100).round(1)
    print(bucket.head(10).to_string())
    print(f"\n有报错的 30 分钟桶数: {len(bucket)} / 全部桶数 "
          f"{len(k.set_index('query_time').is_fail.resample('30min').size())}")


def daily(df: pd.DataFrame) -> None:
    title("2. 分天波动是噪声还是坏日子")
    known = df[df.exec_success.notna()]
    tab = pd.crosstab(known.query_time.dt.date, known.is_fail)
    chi2, p, dof, _ = stats.chi2_contingency(tab)
    print(f"天 × 报错 卡方: chi2={chi2:.2f} dof={dof} p={p:.4f}")
    tab.columns = ["成功", "报错"]
    tab["报错率%"] = (tab["报错"] / tab.sum(axis=1) * 100).round(1)
    tab["滞后>1h条数"] = df[df.schema_lag_h > 1].groupby(
        df[df.schema_lag_h > 1].query_time.dt.date).size().reindex(tab.index).fillna(0).astype(int)
    print(tab.to_string())

    print("\n每天各主题域的报错数（看是否某天某个域集中出问题）：")
    pv = known.pivot_table(index=known.query_time.dt.date, columns="data_domain",
                           values="is_fail", aggfunc="sum").fillna(0).astype(int)
    print(pv.to_string())


def bu_controlled(df: pd.DataFrame) -> None:
    title("3. 部门差异是否只是滞后/提示词的伪装")
    known = df[df.exec_success.notna()].copy()
    known["滞后档"] = np.where(known.schema_lag_h > 1, "滞后>1h", "滞后<=1h")
    known["提示档"] = pd.cut(known.prompt_length, [0, 45, 60, 200],
                            labels=["<=45", "46-60", ">60"])

    print("-- 分层：滞后 <=1h 内，各部门报错率 --")
    sub = known[known.滞后档 == "滞后<=1h"]
    t = sub.groupby("business_unit").agg(n=("is_fail", "size"), fail=("is_fail", "sum"),
                                        rate=("is_fail", "mean"))
    t["rate"] = (t.rate * 100).round(1)
    print(t.to_string())
    chi2, p, _, _ = stats.chi2_contingency(pd.crosstab(sub.business_unit, sub.is_fail))
    print(f"  卡方 p={p:.4f}")

    print("\n-- 分层：各部门内部的提示词长度分布与报错率 --")
    g = known.groupby(["business_unit", "提示档"], observed=True).agg(
        n=("is_fail", "size"), fail=("is_fail", "sum"), rate=("is_fail", "mean"))
    g["rate"] = (g.rate * 100).round(1)
    print(g.to_string())

    print("\n各部门的 prompt_length / confidence / lag 中位数：")
    print(known.groupby("business_unit")[["prompt_length", "confidence_score", "schema_lag_h"]]
          .median().round(2).to_string())


def lag_shape(df: pd.DataFrame) -> None:
    title("4. 快照滞后在 1 小时临界点附近的变化形状")
    known = df[df.exec_success.notna()].copy()
    bins = [0, 0.1, 0.25, 0.5, 0.75, 1.0, 1.2]
    labels = ["0-6min", "6-15min", "15-30min", "30-45min", "45-60min", "60min+"]
    known["lag档"] = pd.cut(known.schema_lag_h, bins, labels=labels, include_lowest=True)
    t = known.groupby("lag档", observed=True).agg(n=("is_fail", "size"), fail=("is_fail", "sum"),
                                                rate=("is_fail", "mean"))
    t["rate"] = (t.rate * 100).round(1)
    print(t.to_string())
    print(f"\n全样本滞后分位: "
          f"50%={known.schema_lag_h.quantile(.5):.2f}h "
          f"90%={known.schema_lag_h.quantile(.9):.2f}h "
          f"95%={known.schema_lag_h.quantile(.95):.2f}h "
          f"99%={known.schema_lag_h.quantile(.99):.2f}h")
    print("\n滞后>1h 的 36 条里，按域分布：")
    print(df[df.schema_lag_h > 1].groupby("data_domain").agg(
        n=("query_id", "size"), fail=("is_fail", "sum")).to_string())


def null_profile(df: pd.DataFrame) -> None:
    title("5. 中断/未回传的 51 条（去重后 49）是否自成一批")
    raw = load_csv(Path("data/sql_queries.csv"), verbose=False)
    nulls = raw[raw.exec_success.isna()]
    print(f"原始 {len(raw)} 行中为空 {len(nulls)} 条；去重后 {int(df.exec_success.isna().sum())} 条")
    print(f"这些行的 query_id 是否唯一: {nulls.query_id.is_unique}")
    print(f"它们的 query_time 分布（按天/小时）：")
    print(nulls.assign(day=pd.to_datetime(nulls.query_time).dt.date,
                       hour=pd.to_datetime(nulls.query_time).dt.hour)
          .groupby(["day"]).size().to_string())
    print("\n如果把这些也算作一次失败（分析师同样要等），损失口径变化：")
    base = int(df.is_fail.sum())
    print(f"  报错 98 次 -> {98 * 75 / 60:.0f} 小时")
    print(f"  报错+中断 147 次 -> {147 * 75 / 60:.0f} 小时（若中断同样损失 75 分钟）")


def main() -> None:
    df = prep()
    clustering(df)
    daily(df)
    bu_controlled(df)
    lag_shape(df)
    null_profile(df)


if __name__ == "__main__":
    main()
