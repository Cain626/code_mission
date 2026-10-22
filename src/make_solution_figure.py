"""生成方案收益对比图（供 reports/解决方案.md 使用）。"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from . import plotting as P

# 数值来自 src/simulate_gate.py 的真实回放结果
SCENARIOS = [
    ("A 修好同步 + 兜底闸门", 85.0, 3.17),
    ("B 自动闸门 15min", 81.8, 3.14),
    ("C 人工闸门 15min（10min/次）", 39.5, 3.14),
    ("D 人工闸门 60min（10min/次）", 16.3, 8.64),
]


def main() -> None:
    print("中文字体:", P.setup_style())

    names = [s[0] for s in SCENARIOS]
    nets = [s[1] for s in SCENARIOS]
    rates = [s[2] for s in SCENARIOS]

    fig, ax = plt.subplots(figsize=(9, 4.2))
    colors = ["#1E8449", "#27AE60", "#E59866", "#C0392B"]
    bars = ax.barh(names[::-1], nets[::-1], color=colors[::-1], height=0.55)

    for bar, rate in zip(bars, rates[::-1]):
        ax.text(bar.get_width() + 1.2, bar.get_y() + bar.get_height() / 2,
                f"净省 {bar.get_width():.0f}h ｜ 剩余报错率 {rate:.1f}%",
                va="center", fontsize=9)
    ax.set_xlim(0, 118)
    ax.set_xlabel("6 天内净节省的分析师时间（小时）")
    ax.set_title("同一批报错数据回放：决定收益的是「校验能不能自动化」")
    ax.axvline(0, color="#333", lw=0.8)
    P.save_fig(fig, "05_方案收益对比")


if __name__ == "__main__":
    main()
