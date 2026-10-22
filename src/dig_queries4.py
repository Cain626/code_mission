"""第五阶段：验证「元数据快照陈旧」是不是唯一主因，并查看同步节奏本身。

要回答：
  1) 提示词长度、部门这两个「显著因子」，是不是滞后造成的假象（混杂）
  2) 快照同步任务本身有多稳定（间隔分布 / 断档）
  3) 断档时段与报错时段是否重合
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


def prep() -> pd.DataFrame:
    df = load_csv(Path("data/sql_queries.csv"), verbose=False).drop_duplicates().copy()
    df["query_time"] = pd.to_datetime(df.query_time, utc=True).dt.tz_convert("Asia/Shanghai")
    df["schema_synced_at"] = pd.to_datetime(df.schema_synced_at, utc=True).dt.tz_convert("Asia/Shanghai")
    df["schema_lag_h"] = (df.query_time - df["schema_synced_at"]).dt.total_seconds() / 3600
    df["is_fail"] = (df.exec_success == 0).astype(float)
    return df


def confound(df: pd.DataFrame) -> None:
    known = df[df.exec_success.notna()].copy()
    print("=" * 90)
    print("1. 提示词长度 / 部门 与滞后的混杂关系")
    print("=" * 90)
    print(f"corr(prompt_length, schema_lag) = "
          f"{known.prompt_length.corr(known.schema_lag_h):.3f}")
    print(f"corr(prompt_length, is_fail)    = {known.prompt_length.corr(known.is_fail):.3f}")
    print(f"corr(schema_lag, is_fail)       = {known.schema_lag_h.corr(known.is_fail):.3f}")

    print("\n各部门的滞后分布（中位/90分位/滞后>15min占比）：")
    g = known.groupby("business_unit").agg(
        滞后中位=("schema_lag_h", "median"),
        滞后p90=("schema_lag_h", lambda s: s.quantile(.9)),
        滞后超15min占比=("schema_lag_h", lambda s: (s > .25).mean()),
        提示词中位=("prompt_length", "median"),
        报错率=("is_fail", "mean"))
    g["滞后超15min占比"] = (g["滞后超15min占比"] * 100).round(1)
    g["报错率"] = (g["报错率"] * 100).round(1)
    print(g.round(2).to_string())

    print("\n各提示词长度档的滞后分布：")
    known["提示档"] = pd.cut(known.prompt_length, [0, 45, 60, 200], labels=["<=45", "46-60", ">60"])
    h = known.groupby("提示档", observed=True).agg(
        滞后中位=("schema_lag_h", "median"),
        滞后超15min占比=("schema_lag_h", lambda s: (s > .25).mean()),
        报错率=("is_fail", "mean"))
    h["滞后超15min占比"] = (h["滞后超15min占比"] * 100).round(1)
    h["报错率"] = (h["报错率"] * 100).round(1)
    print(h.round(2).to_string())


def sync_cadence(df: pd.DataFrame) -> None:
    print("\n" + "=" * 90)
    print("2. 元数据快照的同步节奏")
    print("=" * 90)
    stamps = pd.Series(sorted(df.schema_synced_at.unique()))
    print(f"数据里出现的快照版本数: {len(stamps)}"
          f"（覆盖 {stamps.min():%m-%d %H:%M} ~ {stamps.max():%m-%d %H:%M}，7 天）")
    gaps = stamps.diff().dropna().dt.total_seconds() / 60
    print(f"相邻两个快照版本的间隔（分钟）: 中位={gaps.median():.0f} 均值={gaps.mean():.1f} "
          f"最大={gaps.max():.0f}")
    print("\n间隔分布（分钟）：")
    print(pd.cut(gaps, [0, 5, 10, 15, 20, 30, 60, 120],
                 labels=["<=5", "5-10", "10-15", "15-20", "20-30", "30-60", "60-120"])
          .value_counts().sort_index().to_string())

    print("\n最大的 8 个同步断档：")
    top = pd.DataFrame({"快照时间": stamps.shift(1), "下一次快照": stamps, "间隔分钟": gaps}) \
        .dropna().sort_values("间隔分钟", ascending=False).head(8)
    for _, r in top.iterrows():
        print(f"  {r['快照时间']:%m-%d %H:%M} -> {r['下一次快照']:%m-%d %H:%M}  "
              f"断档 {r['间隔分钟']:.0f} 分钟")

    print("\n每天的快照版本数（正常应为稳定值，明显少说明当天同步有问题）：")
    print(stamps.groupby(stamps.dt.date).size().to_string())


def incident_overlap(df: pd.DataFrame) -> None:
    print("\n" + "=" * 90)
    print("3. 高滞后时段 vs 报错时段的对应关系（按 30 分钟聚合）")
    print("=" * 90)
    d = df.set_index("query_time").sort_index()
    agg = d.resample("30min").agg(
        查询数=("exec_success", "size"),
        报错=("is_fail", "sum"),
        滞后中位=("schema_lag_h", "median"),
        滞后max=("schema_lag_h", "max"))
    agg = agg[agg.查询数 > 0]
    agg["报错率%"] = (agg.报错 / agg.查询数 * 100).round(1)
    hi = agg[agg.滞后中位 > 0.25]
    lo = agg[agg.滞后中位 <= 0.25]
    print(f"高滞后桶（中位>15min）: {len(hi)} 个，平均报错率 {hi['报错率%'].mean():.1f}%，"
          f"合计 {int(hi.报错.sum())} 次报错")
    print(f"低滞后桶            : {len(lo)} 个，平均报错率 {lo['报错率%'].mean():.1f}%，"
          f"合计 {int(lo.报错.sum())} 次报错")
    print("\n报错最多的 10 个半小时候（看滞后是否同步升高）：")
    print(agg.sort_values("报错", ascending=False).head(10).round(2).to_string())


def main() -> None:
    df = prep()
    confound(df)
    sync_cadence(df)
    incident_overlap(df)


if __name__ == "__main__":
    main()
