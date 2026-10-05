from pydantic import BaseModel


class PaginationParams(BaseModel):
    page: int = 1
    page_size: int = 20


def total_pages(total: int, page_size: int) -> int:
    if total == 0:
        return 0
    return (total + page_size - 1) // page_size
