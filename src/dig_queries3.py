"""第四阶段：量化各因子的「覆盖率 × 精确率」，并算清残余未解释部分。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .io_utils import load_csv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOSS_FAIL = 75
LOSS_CHECK = 10


def prep() -> pd.DataFrame:
    df = load_csv(Path("data/sql_queries.csv"), verbose=False).drop_duplicates().copy()
    df["query_time"] = pd.to_datetime(df.query_time, utc=True).dt.tz_convert("Asia/Shanghai")
    df["schema_synced_at"] = pd.to_datetime(df.schema_synced_at, utc=True).dt.tz_convert("Asia/Shanghai")
    df["schema_lag_h"] = (df.query_time - df.schema_synced_at).dt.total_seconds() / 3600
    df["is_fail"] = (df.exec_success == 0).astype(float)
    return df


def rules_table(known: pd.DataFrame) -> None:
    print("=" * 96)
    print("各因子的覆盖能力（在 927 条有结果的查询上）")
    print("=" * 96)
    total_fail = known.is_fail.sum()
    rules = {
        "快照滞后 > 15min": known.schema_lag_h > 0.25,
        "快照滞后 > 30min": known.schema_lag_h > 0.5,
        "快照滞后 > 1h": known.schema_lag_h > 1,
        "提示词 > 60 字": known.prompt_length > 60,
        "置信分 <= 10": known.confidence_score <= 10,
        "供应链/营销 两个部门": known.business_unit.isin(["供应链业务部", "营销增长部"]),
        "滞后>15min 或 提示词>60": (known.schema_lag_h > 0.25) | (known.prompt_length > 60),
        "滞后>15min 或 提示词>60 或 高错部门": (
            (known.schema_lag_h > 0.25) | (known.prompt_length > 60)
            | known.business_unit.isin(["供应链业务部", "营销增长部"])),
    }
    rows = []
    for name, m in rules.items():
        hit = known[m]
        rows.append({
            "因子/规则": name,
            "命中条数": int(m.sum()),
            "命中占比%": round(m.mean() * 100, 1),
            "命中内报错": int(hit.is_fail.sum()),
            "精确率%": round(hit.is_fail.mean() * 100, 1),
            "覆盖报错%": round(hit.is_fail.sum() / total_fail * 100, 1),
        })
    print(pd.DataFrame(rows).to_string(index=False))


def loss_split(df: pd.DataFrame) -> None:
    known = df[df.exec_success.notna()].copy()
    print("\n" + "=" * 96)
    print("损失归因（报错 98 次 × 75 分钟 = 122.5 小时）")
    print("=" * 96)
    groups = {
        "快照滞后 > 1h": known.schema_lag_h > 1,
        "滞后 15min-1h": (known.schema_lag_h > 0.25) & (known.schema_lag_h <= 1),
        "新鲜快照 + 长提示(>60)": (known.schema_lag_h <= 0.25) & (known.prompt_length > 60),
        "新鲜快照 + 短提示(<=60)": (known.schema_lag_h <= 0.25) & (known.prompt_length <= 60),
    }
    rows = []
    for name, m in groups.items():
        f = known[m].is_fail.sum()
        rows.append({"分组": name, "查询数": int(m.sum()), "报错数": int(f),
                     "组内报错率%": round(known[m].is_fail.mean() * 100, 1),
                     "损失h": round(f * LOSS_FAIL / 60, 1),
                     "占全部损失%": round(f / known.is_fail.sum() * 100, 1)})
    t = pd.DataFrame(rows)
    print(t.to_string(index=False))
    print(f"合计损失 {t['损失h'].sum():.1f} 小时")

    print("\n若对高滞后组做前置校验（每次 10 分钟）的账：")
    for thr, label in [(1, ">1h"), (0.25, ">15min")]:
        m = known.schema_lag_h > thr
        n, f = int(m.sum()), int(known[m].is_fail.sum())
        print(f"  阈值{label:6s}: 校验 {n} 次花费 {n * LOSS_CHECK / 60:.1f}h，"
              f"拦截报错 {f} 次挽回 {f * LOSS_FAIL / 60:.1f}h，净收益 "
              f"{(f * LOSS_FAIL - n * LOSS_CHECK) / 60:+.1f}h")


def residual(df: pd.DataFrame) -> None:
    known = df[df.exec_success.notna()].copy()
    print("\n" + "=" * 96)
    print("残余：新鲜快照 + 短提示 里为什么还有 15 次左右报错")
    print("=" * 96)
    m = (known.schema_lag_h <= 0.25) & (known.prompt_length <= 60)
    sub = known[m]
    print(f"该子集 {len(sub)} 条，报错 {int(sub.is_fail.sum())} 条 "
          f"({sub.is_fail.mean():.1%})")
    print("\n按部门：")
    print(sub.groupby("business_unit").agg(n=("is_fail", "size"), fail=("is_fail", "sum"),
                                          rate=("is_fail", "mean")).round(3).to_string())
    print("\n按主题域：")
    print(sub.groupby("data_domain").agg(n=("is_fail", "size"), fail=("is_fail", "sum"),
                                        rate=("is_fail", "mean")).round(3).to_string())
    print(f"\n这些残余报错的置信分分布: 中位={sub[sub.is_fail == 1].confidence_score.median():.0f} "
          f"vs 成功组 {sub[sub.is_fail == 0].confidence_score.median():.0f}")


def main() -> None:
    df = prep()
    known = df[df.exec_success.notna()]
    rules_table(known)
    loss_split(df)
    residual(df)


if __name__ == "__main__":
    main()
