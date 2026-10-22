import yaml
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime
from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import TableInfoStata, DataAgentState
from app.core.log import logger
from app.prompts.prompt_loader import loader_prompt


async def filter_table(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    # 获取流式输出器
    writer = runtime.stream_writer
    # 输出进度状态信息
    # writer("过滤表")
    writer({"stage": "按需过滤指标"})
    try:

        # 获取用户查询
        query = state["query"]
        # 获取合并后的表数据
        table_infos: list[TableInfoStata] = state["table_infos"]

        # 1.使用LLM对组合的表和字段数据根据需求过滤
        # 定义提示词
        prompt = PromptTemplate(template=loader_prompt("filter_table_info"), input_variables=["query", "table_infos"])
        # 定义json格式化输出对象
        output_parser = JsonOutputParser()
        # 组合chain链
        chain = prompt | llm | output_parser
        # 执行chain
        result = await chain.ainvoke(
            {
                "query": query,
                "table_infos": yaml.dump(table_infos, allow_unicode=True, sort_keys=False)
            }
        )
        # https://pyyaml.org/wiki/PyYAMLDocumentation
        # print(f"json转换的结果{yaml.dump(table_infos)}")

        """
         {
         "表名1":["字段1", "字段2", "..."],
         "表名2":["字段1", "字段2", "..."]
        }

        """
        # 2.根据大模型返回根据业务相关的表和列调整table_infos
        # 2.1判断过滤掉大模型返回与业务无关的表和字段 浅拷贝
        for table_info in table_infos[:]:
            # 如果不存在过滤的结果，移除表数据
            if table_info["name"] not in result:
                # 移除表数据
                table_infos.remove(table_info)
            else:
                # 如果存在过滤的结果中， 处理表字段
                # 获取返回指定表的字段列表
                selected_columns = result[table_info["name"]]
                # 遍历组合的字段列表  浅拷贝
                for column in table_info["columns"][:]:
                    # 判断是否存在返回的结果中
                    if column["name"] not in selected_columns:
                        table_info["columns"].remove(column)

        logger.info(f"过滤后的表信息{[table_info['name'] for table_info in table_infos]}")
        # 结果不符合要求（5。如果选择了多张表，需要确保所选字段包含join所需的主外键）
        return {"table_infos": table_infos}
    except Exception as e:
        logger.error(f"过滤后的表信息异常：{str(e)}")
        raise
