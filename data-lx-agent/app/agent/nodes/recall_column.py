import asyncio

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.log import logger
from app.models.qdrant.column_info_qdrant import ColumnInfoQdrant
from app.prompts.prompt_loader import loader_prompt


async def recall_column(state:DataAgentState,runtime:Runtime[DataAgentContext]):
    # 获取流式输出器
    writer = runtime.stream_writer
    # 输出进度状态信息
    # writer("召回列数据")
    writer({"stage": "获取相关列信息"})
    try:
        # 获取状态中用户查询信息
        query =state['query']
        # 获取状态中提取的关键字列表
        keywords =state['keywords']

        # 获取向量服务客户端对象
        embedding_client=runtime.context["embedding_client"]
        # 获取字段向量库
        column_qdrant_repository=runtime.context["column_qdrant_repository"]


        # 1.使用llm扩展关键字
        # 1.1 构建提示词对象
        prompt =PromptTemplate(template=loader_prompt("extend_keywords_for_column_recall"),input_variables=["query"])
        # 1.2 构建结果转换器
        output_parser=JsonOutputParser()
        # 1.3 构建chain执行链
        chain = prompt | llm | output_parser
        # 1.4 执行chain链对接大模型
        result =await chain.ainvoke({"query":query})

        # 2.使用扩展的关键字进行召回字段信息
        # 2.1 根据提取的关键字和适用llm扩张的关键字合并后去重
        keywords =set(keywords+result)
    	    # 2.2 实现字段信息召回
        # 定义字典收集召回的字段信息
        retrieved_columns_map:dict[str,ColumnInfoQdrant]={}
        # 变量所有关键
        for keyword in keywords:
            # 使用向量服务客户端对象关键字进行向量化
            embedding= await embedding_client.aembed_query(keyword)

            # 使用字段向量库查询payload列表
            payloads:list[ColumnInfoQdrant]=await column_qdrant_repository.search(embedding)
            # 遍历字段信息列表
            for payload in payloads:
                # 获取字段id,用于存储时去重
                column_id=payload["id"]
                # 判断是否已经存在收集的字典中
                if column_id not in retrieved_columns_map:
                    retrieved_columns_map[column_id]=payload

        # 将最终去重后，召回的字段信息转换成列表返回
        retrieved_columns= list(retrieved_columns_map.values())
        logger.info(f"召回字段信息:{list(retrieved_columns_map.keys())}")
        # 存储到state中
        return {"retrieved_columns":retrieved_columns}
    except Exception as e:
        logger.error(f"召回字段信息异常{str(e)}")
        raise
