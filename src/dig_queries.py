"""第二阶段：针对第一阶段暴露出的几个疑点做深挖。

疑点：
1) 49 条完全重复记录 与 49 条 exec_success 为空，是不是同一批？
2) 快照滞后 >1h 的 35 条集中在什么时候？是否某个同步任务延迟导致
3) confidence_score 整体与报错率无关，是否被主题域掩盖（辛普森悖论）
4) 时段差异（15点 17.5% vs 19点 4.7%）是真实规律还是噪声
5) 跨域查询（部门查不属于自己的主题域）是否更容易失败
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


def prep() -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = load_csv(Path("data/sql_queries.csv"), verbose=False)
    df = raw.drop_duplicates().copy()
    df["query_time"] = pd.to_datetime(df.query_time, utc=True).dt.tz_convert("Asia/Shanghai")
    df["schema_synced_at"] = pd.to_datetime(df.schema_synced_at, utc=True).dt.tz_convert("Asia/Shanghai")
    df["schema_lag_h"] = (df.query_time - df.schema_synced_at).dt.total_seconds() / 3600
    df["is_fail"] = (df.exec_success == 0).astype(float)
    return raw, df


def q1_dups(raw: pd.DataFrame) -> None:
    title("疑点1：重复记录与「执行中断」是不是同一批")
    dup_mask = raw.duplicated(keep=False)
    dups = raw[dup_mask].sort_values("query_id")
    print(f"参与重复的原始行: {len(dups)}，涉及 query_id: {dups.query_id.nunique()} 个")
    print(f"其中 exec_success 为空的行: {int(dups.exec_success.isna().sum())} / {len(dups)}")
    print(f"全体原始行中为空的行: {int(raw.exec_success.isna().sum())} / {len(raw)}")
    print("\n同一个 query_id 的多条记录，exec_success 是否一致：")
    grp = dups.groupby("query_id").exec_success.nunique(dropna=False)
    print(grp.value_counts().to_string())
    print("\n重复记录样例（同一 query_id 的两种状态）：")
    sample_id = dups.query_id.iloc[0]
    print(dups[dups.query_id == sample_id].to_string())


def q2_lag(df: pd.DataFrame) -> None:
    title("疑点2：快照滞后 >1h 的查询集中在什么时候")
    slow = df[df.schema_lag_h > 1]
    print(f"滞后 >1h 的查询: {len(slow)} 条，报错 {int(slow.is_fail.sum())} 条 "
          f"({slow.is_fail.mean():.1%})")
    print("\n按天：")
    print(slow.groupby(slow.query_time.dt.date).agg(
        条数=("query_id", "size"), 报错=("is_fail", "sum"),
        滞后中位=("schema_lag_h", "median")).round(2).to_string())
    print("\n按小时：")
    print(slow.groupby(slow.query_time.dt.hour).agg(
        条数=("query_id", "size"), 报错=("is_fail", "sum")).to_string())

    print("\n对照：滞后 <=1h 的查询按小时报错率")
    fast = df[df.schema_lag_h <= 1]
    t = fast.groupby(fast.query_time.dt.hour).agg(n=("is_fail", "size"), fail=("is_fail", "sum"))
    t["rate%"] = (t.fail / t.n * 100).round(1)
    print(t.to_string())

    print("\n全量按小时：其中有多少是滞后>1h 贡献的报错")
    allh = df.groupby(df.query_time.dt.hour).agg(n=("is_fail", "size"), fail=("is_fail", "sum"))
    slowh = slow.groupby(slow.query_time.dt.hour)["is_fail"].sum()
    allh["其中滞后>1h报错"] = slowh.reindex(allh.index).fillna(0).astype(int)
    allh["rate%"] = (allh.fail / allh.n * 100).round(1)
    print(allh.to_string())


def q3_confidence(df: pd.DataFrame) -> None:
    title("疑点3：置信分是否被主题域掩盖")
    known = df[df.exec_success.notna()].copy()
    known["conf_bin"] = pd.cut(known.confidence_score, [-1, 10, 20, 30],
                              labels=["低0-10", "中11-20", "高21-30"])
    pv = known.pivot_table(index="data_domain", columns="conf_bin", values="is_fail",
                           aggfunc=["size", "mean"], observed=True)
    print(pv.round(3).to_string())

    print("\n全样本置信分与是否报错的相关性：")
    r, p = stats.pointbiserialr(known.is_fail, known.confidence_score)
    print(f"  point-biserial r={r:.3f} p={p:.3f}")
    r2, p2 = stats.pointbiserialr(known.is_fail, known.prompt_length)
    print(f"  提示词长度 r={r2:.3f} p={p2:.3f}")
    r3, p3 = stats.pointbiserialr(known.is_fail, known.schema_lag_h)
    print(f"  快照滞后 r={r3:.3f} p={p3:.3f}")

    print("\n按主题域内的置信分-报错相关性（是否存在域内有效、整体抵消）：")
    for d, g in known.groupby("data_domain"):
        if g.is_fail.nunique() > 1 and g.confidence_score.nunique() > 1:
            r, p = stats.pointbiserialr(g.is_fail, g.confidence_score)
            print(f"  {d:8s} n={len(g):3d} r={r:+.3f} p={p:.3f}")


def q4_hour(df: pd.DataFrame) -> None:
    title("疑点4：时段差异是真实规律还是噪声")
    known = df[df.exec_success.notna()]
    tab = pd.crosstab(known.query_time.dt.hour, known.is_fail)
    chi2, p, dof, _ = stats.chi2_contingency(tab)
    print(f"小时 × 报错 卡方检验: chi2={chi2:.2f}, dof={dof}, p={p:.4f}")
    print("（p<0.05 说明各时段报错率差异不是随机波动）")

    tab2 = pd.crosstab(known.data_domain, known.is_fail)
    chi2, p, dof, _ = stats.chi2_contingency(tab2)
    print(f"主题域 × 报错 卡方检验: chi2={chi2:.2f}, dof={dof}, p={p:.4f}")

    tab3 = pd.crosstab(known.business_unit, known.is_fail)
    chi2, p, dof, _ = stats.chi2_contingency(tab3)
    print(f"部门 × 报错 卡方检验: chi2={chi2:.2f}, dof={dof}, p={p:.4f}")

    tab4 = pd.crosstab(known.confidence_score, known.is_fail)
    chi2, p, dof, _ = stats.chi2_contingency(tab4)
    print(f"置信分 × 报错 卡方检验: chi2={chi2:.2f}, dof={dof}, p={p:.4f}")


def q5_cross_domain(df: pd.DataFrame) -> None:
    title("疑点5：跨主题域查询是否更容易失败")
    known = df[df.exec_success.notna()].copy()
    # 用「该部门在整体查询中占比最高的主题域」当作它自己的主场
    home = known.groupby("business_unit").data_domain.agg(lambda s: s.value_counts().idxmax())
    known["是否主场"] = [d == home[bu] for bu, d in zip(known.business_unit, known.data_domain)]
    t = known.groupby("是否主场").agg(n=("is_fail", "size"), fail=("is_fail", "sum"),
                                     rate=("is_fail", "mean"))
    t["rate"] = (t["rate"] * 100).round(1)
    print("各自主场域：" + ", ".join(f"{k}->{v}" for k, v in home.items()))
    print(t.to_string())
    chi2, p, dof, _ = stats.chi2_contingency(pd.crosstab(known["是否主场"], known.is_fail))
    print(f"卡方: chi2={chi2:.2f} p={p:.4f}")


def q6_baseline(df: pd.DataFrame) -> None:
    title("疑点6：如果只盯最强的单因子，能拦下多少")
    known = df[df.exec_success.notna()].copy()
    rules = {
        "快照滞后>1h": known.schema_lag_h > 1,
        "提示词>60字": known.prompt_length > 60,
        "置信分<=10": known.confidence_score <= 10,
        "滞后>1h 或 提示词>60": (known.schema_lag_h > 1) | (known.prompt_length > 60),
        "滞后>1h 或 提示>60 或 置信<=10":
            (known.schema_lag_h > 1) | (known.prompt_length > 60) | (known.confidence_score <= 10),
    }
    rows = []
    for name, m in rules.items():
        hit = known[m]
        rows.append({
            "规则": name,
            "命中条数": int(m.sum()),
            "命中中真报错": int(hit.is_fail.sum()),
            "精确率%": round(hit.is_fail.mean() * 100, 1),
            "覆盖率%(占全部报错)": round(hit.is_fail.sum() / known.is_fail.sum() * 100, 1),
        })
    print(pd.DataFrame(rows).to_string(index=False))


def main() -> None:
    raw, df = prep()
    q1_dups(raw)
    q2_lag(df)
    q3_confidence(df)
    q4_hour(df)
    q5_cross_domain(df)
    q6_baseline(df)


if __name__ == "__main__":
    main()
