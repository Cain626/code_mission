import uuid

from fastapi import FastAPI, Request

from app.api.routers.query_router import query_router
from app.core.context import request_id_ctx_var
from app.core.lifespan import lifespan

# 创建Fastapi的实例对象
app = FastAPI(lifespan=lifespan)

# 设置包含路由
app.include_router(query_router)

# 定义中间件组件
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):

    # 赋值异步协程上下文变量 (用户唯一身份标识符)
    request_id_ctx_var.set(uuid.uuid4())

    response = await call_next(request)

    return response