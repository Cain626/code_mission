import asyncio

from fastapi import APIRouter
from fastapi.params import Depends
from starlette.responses import StreamingResponse

from app.api.dependencies import get_query_service
from app.api.schema.query_scheme import QueryScheme
from app.services.query_service import QueryService

# 创建路由实例
query_router = APIRouter()


@query_router.post("/api/query")
async def query(query:QueryScheme,service:QueryService=Depends(get_query_service)):


    return StreamingResponse(service.query(query.query),media_type="text/event-stream")


# @query_router.get("/")
# async def read_root():
#     return {"Hello": "World"}
#
#
# @query_router.get("/items/{item_id}")
# async def read_item(item_id: int, q: str | None = None):
#     return {"item_id": item_id, "q": q}
#
#
# # @query_router.post("/api/query")
# # async def query(query: QueryScheme):
# #     return {"query": query}
#
#
#
#
# async def fake_video_streamer():
#     for i in range(10):
#         await asyncio.sleep(1)
#         yield f"data: stage:{i}\n\n"
#


