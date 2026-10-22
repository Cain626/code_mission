from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import VectorParams, Distance, PointStruct

from app.conf.app_config import app_config
from app.models.qdrant.column_info_qdrant import ColumnInfoQdrant


class ColumnQdrantRepository:
    collection_name = "data-lx-agent-column"

    def __init__(self, client: AsyncQdrantClient):
        self.client = client

    async def ensure_collection(self):
        """
        确保保存列向量的集合存在
        :return:
        """
        if not await self.client.collection_exists(self.collection_name):
            await self.client.create_collection(
                collection_name=self.collection_name,
                # 参数一：向量维度 参数二：相似度算法
                vectors_config=VectorParams(size=app_config.qdrant.embedding_size, distance=Distance.COSINE),
            )

    async def upsert_embedding(self, ids: list[str], embeddings: list[list[float]], payloads: list[ColumnInfoQdrant]):
        """
        保存列信息向量数据到qdrant
        :param ids:
        :param embeddings:
        :param payloads:
        :return:
        """
        # 合并[(id,embedding,payload),(id,embedding,payload),(id,embedding,payload)]
        zipped = list(zip(ids, embeddings, payloads))
        # 构建PointStruct [PointStruct(id,embedding,payload),PointStruct(id,embedding,payload),PointStruct(id,embedding,payload)]
        points = [PointStruct(
            id=id,
            vector=embeddings,
            payload=payload
        ) for id, embeddings, payload in zipped]

        # 保存向量数据到qdrant
        await self.client.upsert(
            collection_name=self.collection_name,
            points=points
        )

    async def search(self, embedding: list[float], score_threshold: float = 0.6, limit: int = 5) -> list[
        ColumnInfoQdrant]:
        # 使用qdrant客户端对象查询指定向量的匹配结果
        results = await self.client.query_points(
            collection_name=self.collection_name,
            query=embedding,
            score_threshold=score_threshold,
            limit=limit
        )

        # 解析获取pointStruct的payload负载结果
        return [point.payload for point in results.points]
