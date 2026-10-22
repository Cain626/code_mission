"""元数据闸门服务：判断字典是否过期、按需重建。

重建很贵（要全量重跑 build_meta_knowledge，涉及向量库和全文索引），所以：
  1) 先用 information_schema 做一次秒级比对，**结构没变就不重建**；
     这解释了为什么零售业务部在陈旧窗口里报错率只有 6.2% —— 它的表结构基本不动。
  2) 真的需要重建时，全局串行 + 60 秒内只跑一次，避免并发请求把机器打满。
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from app.agent.policy import diff_schema
from app.core.log import logger

# 重建节流：60 秒内只允许一次，失败也不立刻重试
REBUILD_TTL_SECONDS = 60
REBUILD_TIMEOUT_SECONDS = 30
DEFAULT_META_CONF = "conf/meta_config.yaml"

_rebuild_lock: asyncio.Lock | None = None
_last_attempt_at: float = 0.0
_last_result: bool = False


def _lock() -> asyncio.Lock:
    """延迟创建锁，避免模块导入时就绑定事件循环。"""
    global _rebuild_lock
    if _rebuild_lock is None:
        _rebuild_lock = asyncio.Lock()
    return _rebuild_lock


class SchemaGuardService:
    def __init__(self, meta_repository, dw_repository):
        self.meta_repository = meta_repository
        self.dw_repository = dw_repository

    async def check(self, table_infos: list[dict] | None):
        """返回 (滞后分钟数, 漂移清单)。漂移为 None 表示没做比对。"""
        lag = await self.meta_repository.get_schema_lag_minutes()
        if lag is None:
            return None, None

        names = [t.get("name") for t in (table_infos or []) if t.get("name")]
        if not names:
            return lag, None

        try:
            live_columns = await self.dw_repository.get_live_columns(names)
        except Exception as e:
            logger.warning(f"活库表结构比对失败，跳过漂移判断: {e}")
            return lag, None

        drift = diff_schema(table_infos or [], live_columns)
        if drift:
            logger.warning(f"检出元数据漂移: {drift}")
        return lag, drift

    async def rebuild(self, conf_path: str = DEFAULT_META_CONF) -> bool:
        """触发一次元数据重建；受 TTL 与全局锁保护。"""
        global _last_attempt_at, _last_result

        now = time.monotonic()
        if now - _last_attempt_at < REBUILD_TTL_SECONDS:
            logger.info("元数据重建处于节流窗口内，直接沿用上次结果")
            return _last_result

        async with _lock():
            # 双检：等锁期间可能已被别的请求重建过
            if time.monotonic() - _last_attempt_at < REBUILD_TTL_SECONDS:
                return _last_result

            _last_attempt_at = time.monotonic()
            _last_result = await self._run_script(conf_path)
            return _last_result

    async def _run_script(self, conf_path: str) -> bool:
        project_root = Path(__file__).resolve().parents[2]
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "app.scripts.build_meta_knowledge",
                "-c", conf_path,
                cwd=str(project_root),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(),
                                               timeout=REBUILD_TIMEOUT_SECONDS)
            if process.returncode == 0:
                logger.info("元数据重建完成")
                # 重建成功后刷新水位
                try:
                    await self.meta_repository.mark_schema_synced("all", "ok")
                except Exception as e:
                    logger.warning(f"写入同步水位失败: {e}")
                return True
            logger.error(f"元数据重建失败(rc={process.returncode}): {stderr.decode(errors='ignore')[:500]}")
            return False
        except asyncio.TimeoutError:
            logger.error(f"元数据重建超时(>{REBUILD_TIMEOUT_SECONDS}s)")
            return False
        except Exception as e:
            logger.error(f"元数据重建异常: {e}")
            return False
