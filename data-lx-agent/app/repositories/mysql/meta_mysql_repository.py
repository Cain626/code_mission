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

