import uuid

from Lib.pathlib import Path
from langchain_huggingface import HuggingFaceEndpointEmbeddings
from omegaconf import OmegaConf

from app.conf.meta_config import MetaConfig
from app.core.log import logger
from app.models.es.value_info_es import ValueInfoEs
from app.models.mysql.column_info_mysql import ColumnInfoMySQL
from app.models.mysql.column_metric_mysql import ColumnMetricMySQL
from app.models.mysql.metric_info_mysql import MetricInfoMySQL
from app.models.mysql.table_info_mysql import TableInfoMySQL
from app.models.qdrant.column_info_qdrant import ColumnInfoQdrant
from app.models.qdrant.metric_info_qdrant import MetricInfoQdrant
from app.repositories.es.value_es_repository import ValueEsRepository
from app.repositories.mysql.dw_mysql_repository import DWMysqlRepository
from app.repositories.mysql.meta_mysql_repository import MetaMysqlRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


class MetaKnowledgeService:
    def __init__(self,
                 meta_mysql_repository: MetaMysqlRepository,
                 dw_mysql_repository: DWMysqlRepository,
                 embedding_client: HuggingFaceEndpointEmbeddings,
                 column_qdrant_repository: ColumnQdrantRepository,
                 value_es_repository: ValueEsRepository,
                 metric_qdrant_repository:MetricQdrantRepository
                 ):
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository
        self.embedding_client = embedding_client
        self.column_qdrant_repository = column_qdrant_repository
        self.vale_es_repository = value_es_repository
        self.metric_qdrant_repository=metric_qdrant_repository

    async def build(self, file_path: Path):
        # 1.加载配置文件
        # 1.1 读取配置内容
        content = OmegaConf.load(file_path)
        # 1.2 定义封装格式
        schema = OmegaConf.structured(MetaConfig)
        # 1.3 合并转换对象
        meta_config: MetaConfig = OmegaConf.to_object(OmegaConf.merge(schema, content))
        logger.info("业务配置加载完成")
        # 2. 处理表信息
        if meta_config.tables:
            # 2.1 保存表信息到meta数据
            column_infos: list[ColumnInfoMySQL] = await self._save_table_info_to_meta_db(meta_config)
            logger.info("保存表信息到meta数据")
            # 2.2 为字段构建向量索引
            await self._save_column_info_to_qdrant(column_infos)
            logger.info("为字段构建向量索引")
            # 2.3 为取值构建全文索引
            await self._save_value_info_to_es(column_infos, meta_config)
            logger.info("为取值构建全文索引")

        # 3. 处理指标信息
        # 3.1 保存指标信息到meta数据
        metric_infos: list[MetricInfoMySQL]=await self._save_metric_info_to_meta_db(meta_config)
        logger.info("保存指标信息到meta数据")

        # 3.2 为指标信息构建向量索引
        await self._save_metric_info_to_qdrant(metric_infos)
        logger.info("为指标信息构建向量索引")





    async def _save_table_info_to_meta_db(self, meta_config: MetaConfig):
        # 创建列表封装表信息
        table_infos: list[TableInfoMySQL] = []
        # 创建列表封装字段信息
        column_infos: list[ColumnInfoMySQL] = []

        for table in meta_config.tables:

            # 创建table_info_mysql对象
            table_info = TableInfoMySQL(
                id=table.name,
                name=table.name,
                role=table.role,
                description=table.description
            )
            table_infos.append(table_info)

            # 查询表中所有字段类型
            column_types: dict[str, str] = await self.dw_mysql_repository.get_column_types(table.name)

            # 处理字段
            for column in table.columns:
                # 查询指定字段的实例值
                column_values: list[str] = await self.dw_mysql_repository.get_column_values(table.name, column.name)

                column_info = ColumnInfoMySQL(
                    id=f"{table.name}.{column.name}",
                    name=column.name,
                    type=column_types[column.name],
                    role=column.role,
                    examples=column_values,
                    description=column.description,
                    alias=column.alias,
                    table_id=table.name
                )
                column_infos.append(column_info)
        # 保存表和字段
        async with self.meta_mysql_repository.session.begin():
            # 保存表
            await self.meta_mysql_repository.save_table_infos(table_infos)
            # 保存字段
            await self.meta_mysql_repository.save_column_infos(column_infos)
        return column_infos

    def _convert_column_info_from_mysql_to_qdrant(self, column_info: ColumnInfoMySQL):

        return ColumnInfoQdrant(
            id=column_info.id,
            name=column_info.name,
            type=column_info.type,
            role=column_info.role,
            examples=column_info.examples,
            description=column_info.description,
            alias=column_info.alias,
            table_id=column_info.table_id
        )

    async def _save_column_info_to_qdrant(self, column_infos: list[ColumnInfoMySQL]):
        # 确保存储字段向量的集合存在
        await self.column_qdrant_repository.ensure_collection()

        # 定义列表收集向量封装信息
        points: list[dict] = []
        # 处理所有字段信息
        for column_info in column_infos:
            # name
            points.append({
                "id": uuid.uuid4(),
                "embedding_text": column_info.name,
                "payload": self._convert_column_info_from_mysql_to_qdrant(column_info)

            })

            # description
            points.append({
                "id": uuid.uuid4(),
                "embedding_text": column_info.description,
                "payload": self._convert_column_info_from_mysql_to_qdrant(column_info)

            })

            # alias
            for alia in column_info.alias:
                points.append({
                    "id": uuid.uuid4(),
                    "embedding_text": alia,
                    "payload": self._convert_column_info_from_mysql_to_qdrant(column_info)

                })

        # 获取所有的向量文本
        embedding_texts: list[str] = [point["embedding_text"] for point in points]
        # 定义转换批次
        batch_size = 10
        # 定义列表收集所有向量
        embeddings = []
        # 遍历批次
        for i in range(0, len(embedding_texts), batch_size):
            # 获取批次数据
            batch_embedding_texts = embedding_texts[i:i + batch_size]
            # 转换向量 list[list[float]]
            batch_embeddings = await self.embedding_client.aembed_documents(batch_embedding_texts)
            # 收集批次数据
            embeddings.extend(batch_embeddings)

        # 获取ids
        ids = [point["id"] for point in points]

        # 获取payload
        payloads = [point["payload"] for point in points]

        # 保存字段向量到qdrant
        await self.column_qdrant_repository.upsert_embedding(ids, embeddings, payloads)

    async def _save_value_info_to_es(self, column_infos: list[ColumnInfoMySQL], meta_config: MetaConfig):
        # 确保存储字段取值的所以存在
        await self.vale_es_repository.ensure_index()
        # 构建字段取值存储结构
        # 定义字典收集字段是否索引的标识
        column2sync: dict[str, bool] = {}
        # 遍历所有配置字段描述
        for table in meta_config.tables:
            for column in table.columns:
                column2sync[column.name] = column.sync

        # 定义列表收集结果
        value_infos: list[ValueInfoEs] = []
        # 遍历所有字段
        for column_info in column_infos:
            # 获取当前字段是否需要索引
            sync = column2sync[column_info.name]
            # 判断
            if sync:
                # 根据当前字段查询所有字段取值
                column_values: list[str] = await self.dw_mysql_repository.get_column_values(column_info.table_id,
                                                                                           column_info.name, 10000)
                # 构建取值结构对象
                for column_value in column_values:
                    value_info = ValueInfoEs(
                        # 表名.列名.值
                        id=f"{column_info.id}.{column_value}",
                        value=column_value,
                        type=column_info.type,
                        column_id=column_info.id,
                        column_name=column_info.name,
                        table_id=column_info.table_id,
                        table_name=column_info.table_id

                    )
                    value_infos.append(value_info)

                # 保存建立索引

        # 保存字段取值到es
        await self.vale_es_repository.upsert_values(value_infos)

    async def _save_metric_info_to_meta_db(self, meta_config:MetaConfig):
        # 定义列表收集指标数据
        metric_infos: list[MetricInfoMySQL] = []
        column_metric_infos: list[ColumnMetricMySQL] = []
        # 判断是否有指标需要同步
        if meta_config.metrics:
            # 遍历指标构建数据
            for metric in meta_config.metrics:
                # 构建数据
                metric_info = MetricInfoMySQL(
                    id=metric.name,
                    name=metric.name,
                    description=metric.description,
                    relevant_columns=metric.relevant_columns,
                    alias=metric.alias

                )
                metric_infos.append(metric_info)

                # 处理字段指标关联表
                for relevant_column in metric.relevant_columns:
                    # 封装结构
                    column_metric = ColumnMetricMySQL(
                        column_id=relevant_column,
                        metric_id=metric.name
                    )
                    column_metric_infos.append(column_metric)

        # 保存指标信息
        async with self.meta_mysql_repository.session.begin():
            await self.meta_mysql_repository.save_metric_infos(metric_infos)
            await self.meta_mysql_repository.save_column_metric_infos(column_metric_infos)

        return metric_infos

    def _convert_metric_info_from_mysql_to_qdrant(self, metric_info:MetricInfoMySQL):
        return MetricInfoQdrant(
            id=metric_info.id,
            name=metric_info.name,
            description=metric_info.description,
            relevant_columns=metric_info.relevant_columns,
            alias=metric_info.alias
        )

    async def _save_metric_info_to_qdrant(self, metric_infos:list[MetricInfoMySQL]):
        # 确保存储向量的集合存在
        await self.metric_qdrant_repository.ensure_collection()
        # 构建存储结构
        # 定义列表收集向量封装信息
        points: list[dict] = []
        # 处理所有字段信息
        for metric_info in metric_infos:
            # name
            points.append({
                "id": uuid.uuid4(),
                "embedding_text": metric_info.name,
                "payload": self._convert_metric_info_from_mysql_to_qdrant(metric_info)

            })

            # description
            points.append({
                "id": uuid.uuid4(),
                "embedding_text": metric_info.description,
                "payload": self._convert_metric_info_from_mysql_to_qdrant(metric_info)

            })

            # alias
            for alia in metric_info.alias:
                points.append({
                    "id": uuid.uuid4(),
                    "embedding_text": alia,
                    "payload": self._convert_metric_info_from_mysql_to_qdrant(metric_info)

                })

        # 获取所有的向量文本
        embedding_texts: list[str] = [point["embedding_text"] for point in points]
        # 定义转换批次
        batch_size = 10
        # 定义列表收集所有向量
        embeddings = []
        # 遍历批次
        for i in range(0, len(embedding_texts), batch_size):
            # 获取批次数据
            batch_embedding_texts = embedding_texts[i:i + batch_size]
            # 转换向量 list[list[float]]
            batch_embeddings = await self.embedding_client.aembed_documents(batch_embedding_texts)
            # 收集批次数据
            embeddings.extend(batch_embeddings)

        # 获取ids
        ids = [point["id"] for point in points]

        # 获取payload
        payloads = [point["payload"] for point in points]

        # 保存字段向量到qdrant
        await self.metric_qdrant_repository.upsert_embeddings(ids, embeddings, payloads)
