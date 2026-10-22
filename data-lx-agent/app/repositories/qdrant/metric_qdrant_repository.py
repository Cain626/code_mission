from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import VectorParams, Distance, PointStruct

from app.conf.app_config import app_config
from app.models.qdrant.metric_info_qdrant import MetricInfoQdrant


class MetricQdrantRepository:
    collection_name = "data-lx-agent-metric"

    def __init__(self, client: AsyncQdrantClient):
        self.client = client

    async def ensure_collection(self):
        """
        确保指标信息存储的集合存在
        :return:
        """
        if not await self.client.collection_exists(self.collection_name):
            await self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=app_config.qdrant.embedding_size, distance=Distance.COSINE)
            )

    async def upsert_embeddings(self, ids: list[str], embeddings: list[list[float]], payloads: list[MetricInfoQdrant],batch_size=5):
        """
        保存指标信息到qdrant
        :param ids:
        :param embeddings:
        :param payloads:
        :return:
        """
        # 整合集合数据
        zipped = list(zip(ids, embeddings, payloads))
        # 循环遍历批次处理
        for i in range(0, len(zipped), batch_size):
            # 获取批量的point数据
            batch = zipped[i:i + batch_size]
            # 构建points,其中点对象PointStruct
            points = [PointStruct(
                id=id,
                vector=embedding,
                payload=payload,

            ) for id, embedding, payload in batch]
            # 批量存储指标
            await self.client.upsert(
                collection_name=self.collection_name,
                points=points
            )

    async def search(self, embedding: list[float], score_threshold: float = 0.6, limit: int = 20) -> list[
        MetricInfoQdrant]:
        # 使用qdrant客户端对象查询指定向量的匹配结果
        results = await self.client.query_points(
            collection_name=self.collection_name,
            query=embedding,
            score_threshold=score_threshold,
            limit=limit
        )

        # 解析获取pointStruct的payload负载结果
        return [point.payload for point in results.points]