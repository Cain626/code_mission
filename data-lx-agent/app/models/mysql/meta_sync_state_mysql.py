from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.mysql.base import Base


class MetaSyncStateMySQL(Base):
    """元数据同步水位表。

    现状：元数据最后一次同步到向量/全文索引的时间没有落库，
    只能从外部埋点推测，导致「字典是否过期」无法在生成 SQL 前判断。
    这张表就是给闸门用的水位线：每次 build_meta_knowledge 成功后写一行。
    """

    __tablename__ = "meta_sync_state"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="自增主键"
    )
    table_name: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        comment="同步范围：all 表示全量重建，否则为具体表名"
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        comment="最近一次成功同步完成的时间"
    )
    status: Mapped[str | None] = mapped_column(
        String(32),
        comment="最近一次同步状态：ok/failed"
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        comment="记录更新时间"
    )
