from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy import bindparam
from sqlalchemy.sql.expression import text


class DWMysqlRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_column_types(self, table_name: str) -> dict[str, str]:
        # 定义sql
        sql = f"show columns  from {table_name}"
        # 执行sql
        result = await self.session.execute(text(sql))
        # 解析结果[(),()]
        return {row.Field: row.Type for row in result.fetchall()}

    async def get_column_values(self, table_name: str, column_name: str, limit: int = 10) -> list[str]:
        # 定义sql
        sql = f"select distinct  {column_name} from {table_name} limit {limit}"
        # 执行sql
        result = await self.session.execute(text(sql))
        # 解析结果
        return result.scalars().fetchall();

    async def get_db_info(self):
        """
        查询数据库环境信息，版本、方言
        :return:
        """
        # 查询数据版本
        result = await self.session.execute(text("select version()"))
        # 解析结果
        version = result.scalar()

        # 查询数据方言
        dialect = self.session.get_bind().dialect.name
        return {"version": version, "dialect": dialect}

    async def validate_sql(self, sql: str):
        """
        验证执行sql
        :param sql:
        :return: 如果sql语法不合法，会抛出异常
        """
        await self.session.execute(text(f"explain {sql}"))

    async def execute_sql(self, sql):
        """
        执行最终的sql语句，获取结果
        :param sql:
        :return:
        """
        result = await self.session.execute(text(sql))
        return [dict(row) for row in result.mappings().fetchall()]

    async def get_live_columns(self, table_names: list[str]) -> dict[str, set[str]]:
        """
        从活库 information_schema 取这些表的真实字段，用于和元数据字典做秒级比对。
        只查结构性字段，不读数据，单次开销远小于一次全量重建。
        :param table_names: 元数据字典里出现的表名
        :return: {表名: {字段名, ...}}；活库里不存在的表返回空集合
        """
        if not table_names:
            return {}
        sql = text(
            "select table_name, column_name from information_schema.columns "
            "where table_schema = database() and table_name in :names"
        ).bindparams(bindparam("names", expanding=True))
        result = await self.session.execute(sql, {"names": list(table_names)})
        columns: dict[str, set[str]] = {name: set() for name in table_names}
        for table_name, column_name in result.fetchall():
            columns.setdefault(table_name, set()).add(column_name)
        return columns
