"""第六阶段：确认「滞后 × 部门/主题域」的交互，并给出最终归因拆解。"""

from __future__ import annotations

import sys
from pathlib import Path

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
    df["是否陈旧"] = df.schema_lag_h > 0.25
    return df


def cross(known: pd.DataFrame, col: str) -> None:
    print(f"\n-- {col} × 快照是否陈旧（>15min） --")
    pv = known.pivot_table(index=col, columns="是否陈旧", values="is_fail",
                           aggfunc=["size", "mean"], observed=True)
    pv.columns = ["新鲜_n", "陈旧_n", "新鲜_报错率", "陈旧_报错率"]
    pv[["新鲜_报错率", "陈旧_报错率"]] = (pv[["新鲜_报错率", "陈旧_报错率"]] * 100).round(1)
    print(pv.to_string())


def main() -> None:
    df = prep()
    known = df[df.exec_success.notna()].copy()
    print("=" * 84)
    print("滞后 × 部门 / 主题域 交互")
    print("=" * 84)
    cross(known, "business_unit")
    cross(known, "data_domain")

    print("\n" + "=" * 84)
    print("置信分在两种情境下是否有用")
    print("=" * 84)
    for label, sub in [("新鲜快照(<=15min)", known[~known.是否陈旧]),
                       ("陈旧快照(>15min)", known[known.是否陈旧])]:
        r, p = stats.pointbiserialr(sub.is_fail, sub.confidence_score)
        lo = sub[sub.confidence_score <= 10]
        hi = sub[sub.confidence_score > 10]
        print(f"{label:18s} n={len(sub):3d} 报错率={sub.is_fail.mean():5.1%} | "
              f"r(置信分)={r:+.3f} p={p:.3f} | 低置信组 {lo.is_fail.mean():5.1%} "
              f"vs 高置信组 {hi.is_fail.mean():5.1%}")

    print("\n" + "=" * 84)
    print("最终归因拆解（927 条有结果的查询）")
    print("=" * 84)
    rows = []
    for label, m in [("快照新鲜 (<=15min)", ~known.是否陈旧), ("快照陈旧 (>15min)", known.是否陈旧)]:
        sub = known[m]
        rows.append({"情境": label, "查询数": len(sub), "占查询%": round(m.mean() * 100, 1),
                     "报错数": int(sub.is_fail.sum()),
                     "报错率%": round(sub.is_fail.mean() * 100, 1),
                     "占总报错%": round(sub.is_fail.sum() / known.is_fail.sum() * 100, 1)})
    print(pd.DataFrame(rows).to_string(index=False))
    print("\n稀缺度对比：28.8% 的查询（快照陈旧）贡献了 78.6% 的报错")
    print("即：把快照陈旧这一条掐掉，理论上可消除 98 次报错里的 77 次（96.2 小时）。")


if __name__ == "__main__":
    main()
