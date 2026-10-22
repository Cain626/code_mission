from langgraph.runtime import Runtime
from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger


async def validate_sql(state:DataAgentState,runtime:Runtime[DataAgentContext]):
    # 获取流式输出器
    writer = runtime.stream_writer
    # 输出进度状态信息
    # writer("校验SQL")
    writer({"stage": "校验SQL合法性"})
    # 获取生成sql
    sql = state["sql"]
    # 获取数仓操作对象
    dw_mysql_repository=runtime.context["dw_mysql_repository"]
    # 捕获验证sql的异常信息
    try:
        # 执行验证sql
        await dw_mysql_repository.validate_sql(sql)
        # 无异常 None
        logger.info(f"sql验证正确：{sql}")
        return {"error":None}
    except Exception as e:
        logger.info(f"sql验证失败：{sql}")
        return {"error":str(e)}