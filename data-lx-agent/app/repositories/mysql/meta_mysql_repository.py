from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.sql.expression import text, select
from app.models.mysql.column_info_mysql import ColumnInfoMySQL
from app.models.mysql.column_metric_mysql import ColumnMetricMySQL
from app.models.mysql.metric_info_mysql import MetricInfoMySQL
from app.models.mysql.table_info_mysql import TableInfoMySQL


class MetaMysqlRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_table_infos(self, table_infos: list[TableInfoMySQL]):
        self.session.add_all(table_infos)

    async def save_column_infos(self, column_infos: list[ColumnInfoMySQL]):
        self.session.add_all(column_infos)

    async def save_metric_infos(self, metric_infos: list[MetricInfoMySQL]):
        self.session.add_all(metric_infos)

    async def save_column_metric_infos(self, column_metric_infos: list[ColumnMetricMySQL]):
        self.session.add_all(column_metric_infos)

    async def get_column_info_by_id(self, relevant_column: str) -> ColumnInfoMySQL:
        """
        查询根据当前字段的id查询meta库中的column_info
        :param relevant_column:
        :return:
        """
        return await self.session.get(ColumnInfoMySQL, relevant_column)

    async def get_key_column_by_table_id(self, table_id: str) -> list[ColumnInfoMySQL]:
        """
        根据表的id查询当前表的主键和外键
        :param table_id:
        :return:
        """
        # 定义sql
        sql = """ \
              select * \
              from column_info \
              where table_id = :table_id \
                and role in ('primary_key', 'foreign_key') \

             """
        # 定义返回结构的类型结构
        query = select(ColumnInfoMySQL).from_statement(text(sql))
        # 执行语句
        result = await self.session.execute(query, {"table_id": table_id})
        # 处理结构
        return result.scalars().fetchall()

    async def get_table_info_by_id(self, table_id: str) -> TableInfoMySQL:
        """
        根据表id查询表信息
        :param table_id:
        :return:
        """

        # 查询返回结果
        return await self.session.get(TableInfoMySQL, table_id)

    async def get_schema_lag_minutes(self) -> float | None:
        """
        元数据字典距离上一次成功同步已经过了多少分钟。
        拿不到（水位表还没建、连接异常）时返回 None，由策略层决定「不阻塞」。
        :return: 分钟数 或 None
        """
        sql = text("select timestampdiff(second, max(last_synced_at), now()) from meta_sync_state")
        try:
            seconds = (await self.session.execute(sql)).scalar()
        except Exception:
            # 水位表缺失属于「测量缺失」，不能当成「数据陈旧」把用户拦住
            return None
        if seconds is None:
            return None
        return max(float(seconds), 0.0) / 60

    async def mark_schema_synced(self, scope: str = "all", status: str = "ok"):
        """
        同步成功后刷新水位
        :param scope: all 或具体表名
        :param status: ok / failed
        """
        sql = text(
            "insert into meta_sync_state(table_name, last_synced_at, status) "
            "values(:scope, now(), :status) "
            "on duplicate key update last_synced_at = now(), status = :status"
        )
        await self.session.execute(sql, {"scope": scope, "status": status})
