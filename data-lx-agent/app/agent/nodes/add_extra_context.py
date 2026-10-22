import asyncio
from datetime import datetime

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState, DateInfoStata
from app.core.log import logger
from app.repositories.mysql.dw_mysql_repository import DWMysqlRepository


async def add_extra_context(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    # 获取流式输出器
    writer = runtime.stream_writer
    # 输出进度状态信息
    writer({"stage":"附加辅助上下文"})

    try:
        # 补充额外的时间信息
        today = datetime.today()
        # 日期
        date = today.strftime("%Y-%m-%d")
        # 星期
        weekday = today.strftime("%A")
        # 季度
        quarter = f"Q{(today.month - 1) // 3 + 1}"
        # 构建时间信息对象
        date_info=DateInfoStata(date=date,weekday=weekday,quarter=quarter)
        # 补充额外的数据库环境信息
        # 获取数仓查询操作对象
        dw_mysql_repository:DWMysqlRepository = runtime.context["dw_mysql_repository"]
        # 执行查询数据库版本和方言
        db_info=await dw_mysql_repository.get_db_info()

        logger.info(f"额外上下文信息添加，日期信息{date_info},数据库信息{db_info}")

        return {"date_info":date_info,"db_info":db_info}
    except Exception as e:
        logger.error(f"额外上下文信息添加异常：{str(e)}")
        raise
