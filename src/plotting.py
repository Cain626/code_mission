"""图表样式：解决 matplotlib 中文乱码与负号显示问题。

Windows 上最典型的现象是标题里的中文变成一串豆腐块 □□□，或者负号变成方块。
只要在每张图之前调用 setup_style() 即可。
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
from matplotlib import font_manager

# 按可用性依次尝试的中文字体（西文优先，中文兜底）
CJK_FONT_CANDIDATES = [
    "Microsoft YaHei",
    "Microsoft YaHei UI",
    "SimHei",
    "DengXian",
    "SimSun",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "PingFang SC",
]

FIG_DIR = Path("reports/figures")


def available_cjk_font() -> str | None:
    """返回本机实际存在的中文字体名。"""
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in CJK_FONT_CANDIDATES:
        if name in installed:
            return name
    return None


def setup_style(theme: str = "whitegrid", font_size: int = 11, dpi: int = 130) -> str:
    """设置全局绘图样式，返回实际使用的中文字体名。"""
    font = available_cjk_font()

    try:
        import seaborn as sns

        sns.set_theme(style=theme, context="notebook")
    except Exception:
        plt.style.use("seaborn-v0_8-whitegrid" if theme == "whitegrid" else "default")

    family = ([font] if font else []) + ["DejaVu Sans", "Arial", "sans-serif"]
    matplotlib.rcParams.update({
        "font.sans-serif": family,
        "font.family": "sans-serif",
        "axes.unicode_minus": False,  # 关键：负号正常显示
        "figure.dpi": dpi,
        "savefig.dpi": dpi,
        "savefig.bbox": "tight",
        "axes.titlesize": font_size + 2,
        "axes.labelsize": font_size,
        "axes.grid": theme != "white",
        "figure.autolayout": True,
    })
    return font or "未找到中文字体（中文可能显示为方块）"


def save_fig(fig, name: str, outdir: str | Path = FIG_DIR) -> Path:
    """保存图片并返回路径。"""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
    if not safe.lower().endswith((".png", ".jpg", ".svg")):
        safe += ".png"
    path = outdir / safe
    fig.savefig(path)
    plt.close(fig)
    return path


# ---------- 常用图 ----------

def bar_top(series, top: int = 10, title: str = "", horizontal: bool = True):
    """类别分布 Top N。"""
    vc = series.value_counts(dropna=False).head(top)
    fig, ax = plt.subplots(figsize=(8, max(3, 0.35 * len(vc) + 1.5)))
    if horizontal:
        ax.barh([str(i) for i in vc.index][::-1], vc.values[::-1], color="#4C78A8")
        ax.set_xlabel("数量")
    else:
        ax.bar([str(i) for i in vc.index], vc.values, color="#4C78A8")
        ax.set_ylabel("数量")
        plt.xticks(rotation=35, ha="right")
    ax.set_title(title or f"{series.name} 分布 Top{top}")
    return fig, ax


def hist_grid(df, cols: list[str] | None = None, ncols: int = 3):
    """多个数值列直方图。"""
    cols = cols or list(df.select_dtypes("number").columns)[:9]
    if not cols:
        raise ValueError("没有可绘制的数值列")
    nrows = (len(cols) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 2.8 * nrows))
    axes = [axes] if nrows * ncols == 1 else axes.ravel()
    for ax, c in zip(axes, cols):
        ax.hist(df[c].dropna(), bins=30, color="#4C78A8", alpha=0.85)
        ax.set_title(str(c))
    for ax in axes[len(cols):]:
        ax.axis("off")
    return fig, axes


def corr_heatmap(df, method: str = "pearson", top: int | None = 20):
    """数值列相关性热力图。"""
    num = df.select_dtypes("number")
    if num.shape[1] < 2:
        raise ValueError("数值列少于 2 个，无法计算相关性")
    corr = num.corr(method=method, numeric_only=True)
    if top and corr.shape[0] > top:
        keep = corr.abs().sum().sort_values(ascending=False).head(top).index
        corr = corr.loc[keep, keep]
    fig, ax = plt.subplots(figsize=(max(5, 0.55 * corr.shape[0] + 3),) * 2)
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr)), [str(c) for c in corr.columns], rotation=45, ha="right")
    ax.set_yticks(range(len(corr)), [str(c) for c in corr.index])
    for i in range(len(corr)):
        for j in range(len(corr)):
            ax.text(j, i, f"{corr.values[i, j]:.2f}", ha="center", va="center",
                    fontsize=7, color="black" if abs(corr.values[i, j]) < 0.6 else "white")
    fig.colorbar(im, ax=ax, shrink=0.8)
    ax.set_title(f"相关性热力图（{method}）")
    return fig, ax
