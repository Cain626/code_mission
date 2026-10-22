from pydantic import BaseModel


class QueryScheme(BaseModel):
    query: str