import asyncio

import yaml
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState, MetricInfoStata
from app.core.log import logger
from app.prompts.prompt_loader import loader_prompt


async def filter_metric(state:DataAgentState,runtime:Runtime[DataAgentContext]):
    # 获取流式输出器
    writer = runtime.stream_writer
    # 输出进度状态信息
    # writer("过滤指标")
    writer({"stage": "按需过滤指标"})
    try:
        # 获取用户查询
        query = state["query"]
        # 获取合并后的指标数据
        metric_infos: list[MetricInfoStata] = state["metric_infos"]

        # 1.使用LLM对指标数据根据需求过滤
        # 定义提示词
        prompt = PromptTemplate(template=loader_prompt("filter_metric_info"), input_variables=["query", "metric_infos"])
        # 定义json格式化输出对象
        output_parser = JsonOutputParser()
        # 组合chain链
        chain = prompt | llm | output_parser
        # 执行chain
        result = await chain.ainvoke({"query": query, "metric_infos": yaml.dump(metric_infos,allow_unicode=True,sort_keys=False)})
        print(f"json转换的结果{yaml.dump(metric_infos,allow_unicode=True,sort_keys=False)}")

        """
        [
             "转正人数",
             "转正率"
        ]
        """
        # 2.根据大模型返回根据业务相关的指标，调整metric_infos
        # 2.1判断过滤掉大模型返回与业务无关的指标 浅拷贝
        for metric_info in metric_infos[:]:
            # 如果不存在过滤的结果，移除表数据
            if metric_info["name"] not in result:
                # 移除表数据
                metric_infos.remove(metric_info)


        logger.info(f"过滤后的表信息{[metric_info["name"] for metric_info in metric_infos]}")
        # 结果不符合要求（5。如果选择了多张表，需要确保所选字段包含join所需的主外键）
        return {"metric_infos": metric_infos}
    except Exception as e:
        logger.error(f"过滤后的表信息异常{str(e)}")
        raise