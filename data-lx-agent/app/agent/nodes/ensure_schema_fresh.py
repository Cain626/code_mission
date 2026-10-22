"""生成 SQL 之前的一道闸门：元数据新鲜度校验。

放在 add_extra_context 之后、generate_sql 之前，因为此时才拿到"这次要查哪些表"，
可以只对这几张表做秒级比对，而不是盲目重建整个字典。

为什么需要它：sql_queries.csv 里 28.8% 的查询发生在元数据滞后 >15 分钟的窗口，
却贡献了 78.6% 的报错；滞后 >1 小时时报错率高达 54.3%。

设计原则：**闸门自身绝不能把主流程搞挂**。任何异常都放行并记日志。
"""

from __future__ import annotations

import os

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.policy import Action, evaluate
from app.agent.state import DataAgentState
from app.core.log import logger
from app.services.schema_guard_service import SchemaGuardService

# 阈值走环境变量，方便灰度期间按部门/实例调整，不用改代码发版
WARN_MINUTES = float(os.getenv("SCHEMA_WARN_MINUTES", "15"))
BLOCK_MINUTES = float(os.getenv("SCHEMA_BLOCK_MINUTES", "60"))
# 默认只告警不拦截：等灰度期验证过误拦率再打开
BLOCK_ON_STALE = os.getenv("SCHEMA_BLOCK_ON_STALE", "false").lower() == "true"


async def ensure_schema_fresh(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"stage": "校验元数据新鲜度"})

    lag: float | None = None
    try:
        guard = SchemaGuardService(
            runtime.context["meta_mysql_repository"],
            runtime.context["dw_mysql_repository"],
        )
        lag, drift = await guard.check(state.get("table_infos"))

        decision = evaluate(lag, drift,
                            warn_minutes=WARN_MINUTES,
                            block_minutes=BLOCK_MINUTES,
                            block_on_stale=BLOCK_ON_STALE)

        if decision.action is Action.REFRESH:
            refresh_ok = await guard.rebuild()
            decision = evaluate(lag, drift, refresh_ok=refresh_ok,
                                warn_minutes=WARN_MINUTES,
                                block_minutes=BLOCK_MINUTES,
                                block_on_stale=BLOCK_ON_STALE)

        logger.info(f"元数据闸门: {decision.action.value} - {decision.reason}")

        if decision.notify_user:
            # 不打断问数，但要让分析师知道这批数可能不准
            writer({"stage": decision.reason})

        if decision.action is Action.BLOCK:
            return {
                "schema_lag_minutes": lag,
                "schema_status": "blocked",
                "blocked_reason": decision.reason,
            }

        return {"schema_lag_minutes": lag, "schema_status": decision.action.value}
    except Exception as e:
        # 闸门出问题不能影响取数本身
        logger.error(f"元数据闸门异常，按放行处理: {e}")
        return {"schema_lag_minutes": lag, "schema_status": "error"}
