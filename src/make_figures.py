"""生成问题定位用的图（4 张）。"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import plotting as P
from .io_utils import load_csv


def prep() -> pd.DataFrame:
    df = load_csv(Path("data/sql_queries.csv"), verbose=False).drop_duplicates().copy()
    df["query_time"] = pd.to_datetime(df.query_time, utc=True).dt.tz_convert("Asia/Shanghai")
    df["schema_synced_at"] = pd.to_datetime(df.schema_synced_at, utc=True).dt.tz_convert("Asia/Shanghai")
    df["schema_lag_h"] = (df.query_time - df["schema_synced_at"]).dt.total_seconds() / 3600
    df["is_fail"] = (df.exec_success == 0).astype(float)
    return df


def fig_lag(known: pd.DataFrame) -> None:
    bins = [0, 0.1, 0.25, 0.5, 0.75, 1.0, 1.2]
    labels = ["0-6分", "6-15分", "15-30分", "30-45分", "45-60分", ">60分"]
    known = known.copy()
    known["b"] = pd.cut(known.schema_lag_h, bins, labels=labels, include_lowest=True)
    g = known.groupby("b", observed=True).agg(n=("is_fail", "size"), r=("is_fail", "mean"))
    g["r"] *= 100

    fig, ax = plt.subplots(figsize=(8, 4.2))
    bars = ax.bar(g.index.astype(str), g.r, color=["#7FB3D5"] * 2 + ["#E59866"] * 3 + ["#C0392B"])
    for b, (n, r) in zip(bars, zip(g.n, g.r)):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.8,
                f"{r:.1f}%\nn={n}", ha="center", va="bottom", fontsize=9)
    ax.axhline(known.is_fail.mean() * 100, ls="--", c="#555", lw=1)
    ax.text(-0.42, known.is_fail.mean() * 100 + 1.2, f"整体 {known.is_fail.mean():.1%}",
            ha="left", fontsize=8, color="#555",
            bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.5))
    ax.set_ylim(0, 65)
    ax.set_ylabel("SQL 执行报错率（%）")
    ax.set_xlabel("生成 SQL 时元数据快照已滞后多久")
    ax.set_title("报错率随元数据快照陈旧度阶梯式上升")
    P.save_fig(fig, "01_滞后与报错率")


def fig_bu(known: pd.DataFrame) -> None:
    known = known.copy()
    known["陈旧"] = np.where(known.schema_lag_h > 0.25, "陈旧(>15min)", "新鲜(<=15min)")
    pv = known.pivot_table(index="business_unit", columns="陈旧", values="is_fail", aggfunc="mean") * 100
    pv = pv.loc[pv["陈旧(>15min)"].sort_values(ascending=False).index]

    x = np.arange(len(pv))
    w = 0.36
    fig, ax = plt.subplots(figsize=(8, 4.2))
    b1 = ax.bar(x - w / 2, pv["新鲜(<=15min)"], w, label="快照新鲜(<=15min)", color="#5DADE2")
    b2 = ax.bar(x + w / 2, pv["陈旧(>15min)"], w, label="快照陈旧(>15min)", color="#C0392B")
    for bars in (b1, b2):
        for b in bars:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.7,
                    f"{b.get_height():.1f}%", ha="center", fontsize=9)
    ax.set_xticks(x, [s.replace("业务部", "") for s in pv.index])
    ax.set_ylabel("报错率（%）")
    ax.set_ylim(0, 45)
    ax.legend(frameon=False)
    ax.set_title("同一批 stale 元数据下，各部暴露程度不同：零售几乎不受影响")
    P.save_fig(fig, "02_部门与滞后交互")


def fig_prompt(known: pd.DataFrame) -> None:
    known = known.copy()
    known["b"] = pd.cut(known.prompt_length, [0, 45, 60, 200], labels=["<=45", "46-60", ">60"])
    marg = (known.groupby("b", observed=True).is_fail.mean() * 100)
    cond = (known[known.schema_lag_h <= 0.25].groupby("b", observed=True).is_fail.mean() * 100)

    x = np.arange(len(marg))
    w = 0.36
    fig, ax = plt.subplots(figsize=(7.2, 4))
    ax.bar(x - w / 2, marg, w, label="不区分快照新鲜度", color="#F0B27A")
    ax.bar(x + w / 2, cond, w, label="只看快照新鲜(<=15min)", color="#5DADE2")
    for i, (a, b) in enumerate(zip(marg, cond)):
        ax.text(i - w / 2, a + 0.3, f"{a:.1f}%", ha="center", fontsize=9)
        ax.text(i + w / 2, b + 0.3, f"{b:.1f}%", ha="center", fontsize=9)
    ax.set_xticks(x, marg.index.astype(str))
    ax.set_xlabel("提示词长度（字符）")
    ax.set_ylabel("报错率（%）")
    ax.set_ylim(0, 18)
    ax.legend(frameon=False)
    ax.set_title("提示词长度的“影响”在控制元数据陈旧度后基本消失")
    P.save_fig(fig, "03_提示词长度与滞后混杂")


def fig_daily(known: pd.DataFrame) -> None:
    d = known.set_index("query_time").sort_index()
    daily = d.resample("D").agg(报错=("is_fail", "sum"), 查询=("is_fail", "size"))
    daily["率"] = daily.报错 / daily.查询 * 100
    lag90 = d.schema_lag_h.resample("D").quantile(0.9)
    stale_share = d.schema_lag_h.resample("D").apply(lambda s: (s > 0.25).mean() * 100)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(range(len(daily)), daily.率, color="#7FB3D5", label="报错率")
    ax.set_ylabel("报错率（%）", color="#2C3E50")
    ax.set_ylim(0, 22)
    ax2 = ax.twinx()
    ax2.plot(range(len(daily)), stale_share.values, "o-", color="#C0392B",
             label="陈旧快照查询占比")
    ax2.set_ylabel("陈旧快照(>15min)查询占比（%）", color="#C0392B")
    ax2.set_ylim(0, 45)
    ax.set_xticks(range(len(daily)), [f"{t:%m-%d}" for t in daily.index])
    r = np.corrcoef(daily.率.values, stale_share.values)[0, 1]
    ax.set_title(f"每日报错率与当天陈旧快照占比（日相关 r={r:.2f}；单日仅约 130 条，波动大）",
                 fontsize=11)
    lines = ax.get_legend_handles_labels()[0] + ax2.get_legend_handles_labels()[0]
    labels = ax.get_legend_handles_labels()[1] + ax2.get_legend_handles_labels()[1]
    ax.legend(lines, labels, loc="upper left", frameon=False, fontsize=8)
    P.save_fig(fig, "04_每日报错与陈旧占比")


def main() -> None:
    font = P.setup_style()
    print("中文字体:", font)
    df = prep()
    known = df[df.exec_success.notna()]
    fig_lag(known)
    fig_bu(known)
    fig_prompt(known)
    fig_daily(known)
    print("已生成:")
    for p in sorted(Path("reports/figures").glob("0*.png")):
        print("  ", p)


if __name__ == "__main__":
    main()
