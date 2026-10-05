from enum import StrEnum

from sqlalchemy import Enum as SAEnum


def pg_enum[E: StrEnum](enum_cls: type[E], name: str) -> SAEnum:
    """A native Postgres ENUM storing the string .value, not the Python member name."""
    return SAEnum(enum_cls, name=name, values_callable=lambda cls: [member.value for member in cls])
