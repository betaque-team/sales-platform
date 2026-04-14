from pydantic import BaseModel


class PaginationParams(BaseModel):
    page: int = 1
    per_page: int = 50


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    per_page: int
    pages: int
