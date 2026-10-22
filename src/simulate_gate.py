"""在真实数据上回放「前置闸门」的效果，算清每个方案的净收益。

口径（任务书给定）：
  - 一次执行报错 → 分析师损失 75 分钟
  - 一次前置校验 → 花费 10 分钟

本脚本额外明确三个建模假设（都有名字，方便反驳）：
  1. check_cost：闸门单次成本。人工校验按 10 分钟；自动刷新元数据是秒级，按 0.5 分钟。
  2. p（refresh_ok）：触发刷新后成功的概率。成功 → 该查询报错率回落到「新鲜快照」基线；
     失败 → 拦下不执行，不算 75 分钟盲查，但这次拿不到数，按一次重新提问 10 分钟计。
  3. 未被闸门触发的查询，按数据里的真实结果计（只有「修好同步」这一种方案是反事实推算，
     用新鲜窗口的 3.18% 基线放大到全量）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from .io_utils import load_csv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOSS_FAIL_MIN = 75
LOSS_CHECK_MIN = 10
AUTO_COST_MIN = 0.5
REASK_MIN = 10


def prep() -> pd.DataFrame:
    df = load_csv(Path("data/sql_queries.csv"), verbose=False).drop_duplicates().copy()
    df["query_time"] = pd.to_datetime(df.query_time, utc=True).dt.tz_convert("Asia/Shanghai")
    df["schema_synced_at"] = pd.to_datetime(df.schema_synced_at, utc=True).dt.tz_convert("Asia/Shanghai")
    df["schema_lag_h"] = (df.query_time - df["schema_synced_at"]).dt.total_seconds() / 3600
    df["is_fail"] = (df.exec_success == 0).astype(float)
    return df


def gate(known: pd.DataFrame, base_rate: float, thr_h: float, p: float,
         check_min: float, loss_now: float) -> dict:
    stale = known.schema_lag_h > thr_h
    n_stale = int(stale.sum())
    n_blocked = int(round(n_stale * (1 - p)))
    fail_after = known[~stale].is_fail.sum() + p * base_rate * n_stale
    cost_h = (n_stale * check_min + n_blocked * REASK_MIN) / 60
    loss_h = fail_after * LOSS_FAIL_MIN / 60
    return {"触发": n_stale, "拦截未取数": n_blocked, "校验成本h": round(cost_h, 1),
            "剩余报错": round(float(fail_after), 1), "总损失h": round(loss_h, 1),
            "净节省h": round(loss_now - loss_h - cost_h, 1)}


def main() -> None:
    df = prep()
    known = df[df.exec_success.notna()]
    n_known = len(known)
    base = known.is_fail.sum()
    loss_now = base * LOSS_FAIL_MIN / 60
    base_rate = known[known.schema_lag_h <= .25].is_fail.mean()

    print("=" * 104)
    print(f"回放口径：{len(df)} 条查询，{n_known} 条有执行结果；新鲜基线报错率 {base_rate:.2%}；"
          f"现状总损失 {loss_now:.1f} 小时")
    print("=" * 104)

    rows = [{"方案": "现状（不做任何事）", "触发": 0, "拦截未取数": 0, "校验成本h": 0.0,
             "剩余报错": round(float(base), 1), "总损失h": round(loss_now, 1), "净节省h": 0.0}]

    # A：同步彻底修好 —— 反事实：全量按新鲜基线的 3.18% 估算
    fail_a = base_rate * n_known
    rows.append({"方案": "A 修好同步（陈旧窗口消失）", "触发": 0, "拦截未取数": 0,
                 "校验成本h": 0.0, "剩余报错": round(fail_a, 1),
                 "总损失h": round(fail_a * LOSS_FAIL_MIN / 60, 1),
                 "净节省h": round(loss_now - fail_a * LOSS_FAIL_MIN / 60, 1)})

    for name, thr, p, cost in [
        ("B 自动闸门 15min（刷新成功 95%）", 0.25, 0.95, AUTO_COST_MIN),
        ("B- 自动闸门 15min（刷新成功 80%）", 0.25, 0.80, AUTO_COST_MIN),
        ("B+ 自动闸门 30min（刷新成功 95%）", 0.50, 0.95, AUTO_COST_MIN),
        ("C 人工闸门 15min（10min/次，95%）", 0.25, 0.95, LOSS_CHECK_MIN),
        ("C- 人工闸门 15min（10min/次，80%）", 0.25, 0.80, LOSS_CHECK_MIN),
        ("D 人工闸门 60min（10min/次，95%）", 1.00, 0.95, LOSS_CHECK_MIN),
    ]:
        r = gate(known, base_rate, thr, p, cost, loss_now)
        r["方案"] = name
        rows.append(r)

    # E：修好同步 + 保留闸门兜底（5% 查询仍会触发）
    residual = 0.05
    fail_e = base_rate * n_known * ((1 - residual) + residual * 0.95)
    cost_e = n_known * residual * AUTO_COST_MIN / 60 + n_known * residual * 0.05 * REASK_MIN / 60
    rows.append({"方案": "E A+兜底闸门（5% 残留触发）", "触发": int(n_known * residual),
                 "拦截未取数": int(n_known * residual * 0.05), "校验成本h": round(cost_e, 1),
                 "剩余报错": round(fail_e, 1),
                 "总损失h": round(fail_e * LOSS_FAIL_MIN / 60, 1),
                 "净节省h": round(loss_now - fail_e * LOSS_FAIL_MIN / 60 - cost_e, 1)})

    t = pd.DataFrame(rows)[["方案", "触发", "校验成本h", "剩余报错", "拦截未取数", "总损失h", "净节省h"]]
    print(t.to_string(index=False))
    print("\n（净节省 = 现状损失 - 方案损失 - 校验成本；拦截后重新提问按 10 分钟计入成本）")

    print("\n" + "-" * 104)
    print("折算每周（样本 6 天 → 7 天）与落地后的报错率：")
    for _, r in t.iterrows():
        print(f"  {r['方案']:34s} 净节省 {r['净节省h'] * 7 / 6:6.1f} h/周"
              f"   剩余报错率 {r['剩余报错'] / n_known:5.2%}")

    print("\n" + "-" * 104)
    print("敏感性：自动闸门（0.5 分钟/次）在不同阈值 × 刷新成功率下的净节省（小时）")
    print(f"{'阈值':>6} | " + " | ".join(f"p={p:.0%}" for p in (0.6, 0.7, 0.8, 0.9, 0.95, 1.0)))
    for thr, label in [(0.1, "6min"), (0.25, "15min"), (0.5, "30min"), (0.75, "45min"), (1.0, "60min")]:
        cells = []
        for p in (0.6, 0.7, 0.8, 0.9, 0.95, 1.0):
            cells.append(f"{gate(known, base_rate, thr, p, AUTO_COST_MIN, loss_now)['净节省h']:+6.1f}")
        print(f"{label:>6} | " + " | ".join(f"{c:>6}" for c in cells))

    print("\n" + "-" * 104)
    print("分部门最优阈值（自动闸门，p=95%，0.5 分钟/次）—— 数据支持差异化阈值")
    for bu, sub in known.groupby("business_unit"):
        sub = sub.copy()
        br = sub[sub.schema_lag_h <= 0.25].is_fail.mean()
        ln = sub.is_fail.sum() * LOSS_FAIL_MIN / 60
        best = []
        for thr, label in [(0.1, "6min"), (0.25, "15min"), (0.5, "30min"), (1.0, "60min"), (99, "不拦")]:
            r = gate(sub, br, thr, 0.95, AUTO_COST_MIN, ln)
            best.append((r["净节省h"], label, r["触发"]))
        best.sort(reverse=True)
        print(f"  {bu:8s} 现状报错 {int(sub.is_fail.sum()):2d} 次 | 最优阈值 {best[0][1]:>5s} "
              f"（触发 {best[0][2]:3d} 次，净省 {best[0][0]:5.1f}h）| 次优 {best[1][1]}"
              f"（净省 {best[1][0]:5.1f}h）")


if __name__ == "__main__":
    main()
