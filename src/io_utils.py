"""CSV 读取工具：自动探测编码与分隔符。

中文业务数据最常见的坑就是编码（utf-8 / gbk / gb18030）和分隔符（逗号 / 分号 / 制表符）
不匹配，导致读进来一堆乱码或者只剩一列。这里统一处理掉。
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pandas as pd

# 覆盖中文 Windows / macOS / Linux 导出 CSV 的常见编码，按优先级排列
ENCODING_CANDIDATES = (
    "utf-8-sig",  # Excel 另存为「CSV UTF-8」时带 BOM
    "utf-8",
    "gb18030",  # 兼容 gbk / gb2312，范围最大
    "gbk",
    "big5",
    "utf-16",
)

_READ_BYTES = 1 << 20  # 探测时只读前 1MB


def _sample(path: Path) -> bytes:
    with open(path, "rb") as f:
        return f.read(_READ_BYTES)


def _decodes(raw: bytes, enc: str) -> bool:
    """判断 raw 能否用 enc 严格解码。

    探测时只读文件前 1MB，末尾可能正好切在一个多字节字符中间，
    这种「截断导致的末尾不完整」不算真实解码失败，需要放行。
    """
    try:
        raw.decode(enc)
        return True
    except LookupError:
        return False
    except UnicodeDecodeError as e:
        if e.start >= len(raw) - 8:
            return True
        return False


def detect_encoding(path: str | Path) -> str:
    """返回能够完整解码文件开头的最佳编码。"""
    path = Path(path)
    raw = _sample(path)

    # BOM 优先判定
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"

    # UTF-8 的字节模式足够独特，能通过严格解码基本就可以确定是 UTF-8
    if _decodes(raw, "utf-8"):
        return "utf-8"

    # 再用 charset-normalizer 猜一次（对 GBK / Big5 更准）
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        if best and best.encoding and _decodes(raw, best.encoding):
            return best.encoding
    except Exception:
        pass

    for enc in ENCODING_CANDIDATES:
        if enc in ("utf-8", "utf-8-sig"):
            continue
        if _decodes(raw, enc):
            return enc

    return "utf-8"



def detect_sep(path: str | Path, encoding: str, candidates: str = ",;\t|") -> str:
    """探测分隔符，优先用 csv.Sniffer，失败则按首行各符号出现次数投票。"""
    path = Path(path)
    text = _sample(path).decode(encoding, errors="replace")
    head = "\n".join(text.splitlines()[:20])

    try:
        dialect = csv.Sniffer().sniff(head, delimiters=candidates)
        return dialect.delimiter
    except csv.Error:
        pass

    first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
    counts = {sep: first_line.count(sep) for sep in candidates}
    best_sep, best_cnt = max(counts.items(), key=lambda kv: kv[1])
    return best_sep if best_cnt > 0 else ","


def load_csv(
    path: str | Path,
    encoding: str | None = None,
    sep: str | None = None,
    nrows: int | None = None,
    drop_empty_cols: bool = True,
    verbose: bool = True,
) -> pd.DataFrame:
    """健壮地读取 CSV。

    - 不传 encoding / sep 时自动探测
    - 去掉列名首尾空白、去重空列
    - 默认不把空字符串当 NaN 之外的特殊值处理，保留原始语义
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    enc = encoding or detect_encoding(path)
    delimiter = sep or detect_sep(path, enc)

    df = pd.read_csv(
        path,
        encoding=enc,
        sep=delimiter,
        nrows=nrows,
        low_memory=False,
        skipinitialspace=True,
    )

    df.columns = [str(c).strip() for c in df.columns]
    if drop_empty_cols:
        empty = [c for c in df.columns if df[c].isna().all()]
        if empty:
            df = df.drop(columns=empty)

    if verbose:
        print(f"[load_csv] {path.name}  编码={enc}  分隔符={delimiter!r}  "
              f"形状={df.shape[0]}行 × {df.shape[1]}列")

    return df


def to_markdown_table(df: pd.DataFrame, index: bool = False) -> str:
    """DataFrame 转 Markdown 表格（不依赖 tabulate）。"""
    if df.empty:
        return "_(空)_"
    d = df.reset_index() if index else df
    cols = [str(c) for c in d.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in d.iterrows():
        cells = []
        for v in row:
            if pd.isna(v):
                cells.append("")
            elif isinstance(v, float):
                cells.append(f"{v:g}")
            else:
                cells.append(str(v).replace("|", "\\|").replace("\n", " "))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    p = sys.argv[1] if len(sys.argv) > 1 else ""
    if not p:
        raise SystemExit("用法: python -m src.io_utils <csv路径>")
    print("编码:", detect_encoding(p))
    print("分隔符:", repr(detect_sep(p, detect_encoding(p))))
    print(load_csv(p).head().to_string())
