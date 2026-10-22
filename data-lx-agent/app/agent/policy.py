"""元数据新鲜度策略与 SQL 错误归类。

刻意做成**零第三方依赖**的纯函数模块：既能被 LangGraph 节点调用，
也能脱离 Docker / MySQL / 大模型单独跑自测（`python app/agent/policy.py`）。

判据来自 sql_queries.csv 的实测结论：
  - 快照滞后 <= 15 分钟：报错率 2.6%~3.8%（基线）
  - 滞后 15~60 分钟：报错率 20%~33%
  - 滞后 > 60 分钟：报错率 54.3%
但「滞后」只是触发器，真正决定风险的是**表结构有没有变**：
零售业务部在陈旧窗口里报错率只有 6.2%，因为它的表结构基本不动。
所以策略是「滞后先告警 → 用活库 information_schema 做一次秒级比对 → 只在真的漂移时才重建」。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

DEFAULT_WARN_MINUTES = 15.0
DEFAULT_BLOCK_MINUTES = 60.0


class Action(str, Enum):
    PASS = "pass"        # 放行
    REFRESH = "refresh"  # 结构漂移，重建元数据后再继续
    BLOCK = "block"      # 拦下不执行，直接告诉分析师原因


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str
    notify_user: bool = False


def evaluate(
    lag_minutes: float | None,
    drift: list[str] | None,
    *,
    refresh_ok: bool | None = None,
    warn_minutes: float = DEFAULT_WARN_MINUTES,
    block_minutes: float = DEFAULT_BLOCK_MINUTES,
    block_on_stale: bool = False,
) -> Decision:
    """判断这一步该放行、该重建、还是该拦。

    lag_minutes : 元数据最后一次同步距今的分钟数；None = 拿不到（同步表未建/查询失败）
    drift       : 活库表结构与元数据字典的差异清单；None = 没做比对
    refresh_ok  : 上一次重建是否成功；None = 还没尝试过
    block_on_stale : 刷新失败时是否硬拦。默认 False，先只告警，等线上误拦率验证后再打开。
    """
    if lag_minutes is None:
        return Decision(Action.PASS, "无法获取元数据同步时间，跳过新鲜度校验")

    if lag_minutes <= warn_minutes:
        return Decision(Action.PASS, f"元数据新鲜（滞后 {lag_minutes:.0f} 分钟）")

    # 1) 廉价比对已经做过，且结构没变 —— 陈旧但无害，直接放行
    if drift is not None and not drift:
        return Decision(Action.PASS,
                        f"字典滞后 {lag_minutes:.0f} 分钟，但活库表结构未变，放行")

    # 2) 确有漂移，或没能比对 → 需要重建
    if refresh_ok is None:
        why = f"检出结构漂移 {len(drift)} 处" if drift else "无法比对活库结构"
        return Decision(Action.REFRESH, f"元数据滞后 {lag_minutes:.0f} 分钟，{why}，触发重建")

    if refresh_ok:
        return Decision(Action.PASS, "元数据已重建，继续生成")

    # 3) 重建失败
    if lag_minutes > block_minutes and block_on_stale:
        return Decision(Action.BLOCK,
                        f"元数据滞后 {lag_minutes:.0f} 分钟且重建失败，"
                        f"为避免生成必然报错的 SQL 已拦截", notify_user=True)
    return Decision(Action.PASS,
                    f"元数据滞后 {lag_minutes:.0f} 分钟且重建失败，继续生成但已标注风险",
                    notify_user=True)


def diff_schema(meta_tables: list[dict], live_columns: dict[str, set[str]]) -> list[str]:
    """比对元数据字典与活库表结构，返回差异描述。

    meta_tables : [{"name": "fact_order", "columns": [{"name": "order_id"}, ...]}, ...]
    live_columns: {"fact_order": {"order_id", "amount", ...}, ...}；缺表则用空集合表示
    """
    drift: list[str] = []
    for table in meta_tables:
        name = table.get("name")
        if not name:
            continue
        live = live_columns.get(name)
        if live is None:
            drift.append(f"表 {name} 在活库中不存在")
            continue
        want = {c.get("name") for c in table.get("columns") or [] if c.get("name")}
        missing = sorted(want - live)
        if missing:
            drift.append(f"表 {name} 缺少字段 {', '.join(missing)}")
    return drift


# ---------------- 执行报错归类 ----------------

class ErrorKind(str, Enum):
    METADATA = "metadata"      # 表/字段不存在 —— 元数据问题，刷新后重试
    SYNTAX = "syntax"          # 语法错误 —— 让模型改一次
    TYPE = "type"              # 类型/取值不匹配 —— 让模型改一次
    PERMISSION = "permission"  # 权限 —— 改 SQL 没用
    TIMEOUT = "timeout"        # 超时/锁 —— 重试或改 SQL 都可能没用
    UNKNOWN = "unknown"


_PATTERNS: list[tuple[ErrorKind, str]] = [
    (ErrorKind.METADATA, r"unknown column|no such column|doesn'?t exist|does not exist|"
                         r"unknown table|invalid column|字段不存在|列不存在|表不存在|未知列"),
    (ErrorKind.PERMISSION, r"access denied|permission denied|not authorized|权限|拒绝访问"),
    (ErrorKind.TIMEOUT, r"timeout|timed out|lock wait|deadlock|超时|死锁"),
    (ErrorKind.SYNTAX, r"syntax error|syntax|parse error|语法"),
    (ErrorKind.TYPE, r"incorrect .*value|incorrect .*type|type mismatch|invalid input syntax|"
                     r"cannot cast|类型不匹配|转换失败"),
]

_RETRYABLE = {ErrorKind.METADATA, ErrorKind.SYNTAX, ErrorKind.TYPE}


def classify_sql_error(message: str | None) -> ErrorKind:
    if not message:
        return ErrorKind.UNKNOWN
    text = str(message).lower()
    for kind, pattern in _PATTERNS:
        if re.search(pattern, text):
            return kind
    return ErrorKind.UNKNOWN


def should_retry(kind: ErrorKind, already_retried: bool) -> bool:
    """只对「改一版大概率能过」的错误重试，且最多一次。"""
    return (kind in _RETRYABLE) and not already_retried


# ---------------- 自测 ----------------

if __name__ == "__main__":
    cases = [
        ((5, None), {}, Action.PASS, "新鲜直接放行"),
        ((20, []), {}, Action.PASS, "滞后但结构未变"),
        ((20, ["表 a 缺少字段 b"]), {}, Action.REFRESH, "滞后且检出漂移 → 先重建"),
        ((20, ["表 a 缺少字段 b"]), dict(refresh_ok=True), Action.PASS, "重建成功继续"),
        ((20, ["表 a 缺少字段 b"]), dict(refresh_ok=False), Action.PASS, "重建失败仅告警"),
        ((90, ["表 a 缺少字段 b"]), dict(refresh_ok=False), Action.PASS, "未开硬拦不阻塞"),
        ((90, ["表 a 缺少字段 b"]), dict(refresh_ok=False, block_on_stale=True), Action.BLOCK, "开硬拦后拦截"),
        ((None, None), {}, Action.PASS, "拿不到同步时间不阻塞"),
    ]
    for (lag, drift), kwargs, expect, desc in cases:
        got = evaluate(lag, drift, **kwargs)
        assert got.action == expect, f"{desc}: 期望 {expect}, 实际 {got.action} ({got.reason})"
        print(f"  ✓ {desc:22s} -> {got.action.value:8s} {got.reason}")

    meta = [{"name": "fact_order", "columns": [{"name": "order_id"}, {"name": "amount"}]},
            {"name": "dim_gone", "columns": [{"name": "id"}]}]
    live = {"fact_order": {"order_id", "amount", "city"}}
    drift = diff_schema(meta, live)
    assert len(drift) == 1 and "dim_gone" in drift[0], drift
    print(f"  ✓ 结构比对 -> {drift}")
    assert diff_schema(meta[:1], live) == [], "结构一致时应无差异"

    errs = [
        ("""(1054, "Unknown column 'amount' in 'field list'")""", ErrorKind.METADATA),
        ("Table 'dw.fact_order' doesn't exist", ErrorKind.METADATA),
        ("You have an error in your SQL syntax near 'group'", ErrorKind.SYNTAX),
        ("Incorrect datetime value: '2026-13-01'", ErrorKind.TYPE),
        ("Access denied for user 'root'", ErrorKind.PERMISSION),
        ("Lock wait timeout exceeded", ErrorKind.TIMEOUT),
        ("", ErrorKind.UNKNOWN),
    ]
    for msg, expect in errs:
        got = classify_sql_error(msg)
        assert got == expect, f"{msg!r}: 期望 {expect}, 实际 {got}"
    print(f"  ✓ 报错归类 {len(errs)} 条全部命中")

    assert should_retry(ErrorKind.METADATA, False) and not should_retry(ErrorKind.METADATA, True)
    assert not should_retry(ErrorKind.PERMISSION, False)
    print("  ✓ 重试策略符合预期")
    print("\npolicy 自测全部通过")
