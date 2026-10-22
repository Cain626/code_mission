import asyncio
import random
from typing import Optional
from qdrant_client import AsyncQdrantClient, models
from app.conf.app_config import QdrantConfig, app_config


class QdrantClientManager:
    """Qdrant 向量数据库异步客户端管理器"""

    def __init__(self, qdrant_config: QdrantConfig):
        """初始化管理器，保存配置信息，客户端实例稍后创建"""
        self.qdrant_config = qdrant_config
        self.client: Optional[AsyncQdrantClient] = None

    def _get_url(self) -> str:
        """拼接 Qdrant 服务地址"""
        return f"http://{self.qdrant_config.host}:{self.qdrant_config.port}"

    def init(self) -> None:
        """创建异步客户端实例"""
        self.client = AsyncQdrantClient(self._get_url())

    async def close(self) -> None:
        """关闭客户端，释放连接资源"""
        if self.client:
            await self.client.close()


# 全局客户端管理器实例
qdrant_client_manager = QdrantClientManager(app_config.qdrant)


if __name__ == "__main__":
    # 初始化客户端
    qdrant_client_manager.init()

    async def test():
        """测试流程：创建集合并入库 → 批量插入向量 → 相似度检索"""
        client = qdrant_client_manager.client

        # 1. 检查集合是否存在，不存在则创建
        if not await client.collection_exists("my_collection"):
            await client.create_collection(
                collection_name="my_collection",
                vectors_config=models.VectorParams(
                    size=10,
                    distance=models.Distance.COSINE
                ),
            )

        # 2. 批量插入 100 条 10 维随机向量
        await client.upsert(
            collection_name="my_collection",
            points=[
                models.PointStruct(
                    id=i,
                    vector=[random.random() for _ in range(10)]
                )
                for i in range(100)
            ],
        )

        # 3. 用随机向量检索最相似的 10 条结果
        result = await client.query_points(
            collection_name="my_collection",
            query=[random.random() for _ in range(10)],
            limit=10,
            score_threshold=0.5,
        )

        # 输出检索结果
        print(result.points)

    asyncio.run(test())