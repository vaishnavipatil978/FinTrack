"""seed system categories

Revision ID: 308509395ce3
Revises: 3696c7e38f47
Create Date: 2026-09-30 11:13:51.672671
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PGEnum

# revision identifiers, used by Alembic.
revision: str = "308509395ce3"
down_revision: Union[str, None] = "3696c7e38f47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# FR-CAT-01: system default categories available to every user (user_id IS NULL).
_SYSTEM_CATEGORIES: list[tuple[str, str]] = [
    ("Salary", "INCOME"),
    ("Other Income", "INCOME"),
    ("Food", "EXPENSE"),
    ("Transport", "EXPENSE"),
    ("Rent", "EXPENSE"),
    ("Shopping", "EXPENSE"),
    ("Utilities", "EXPENSE"),
    ("Entertainment", "EXPENSE"),
    ("Healthcare", "EXPENSE"),
    ("Other Expense", "EXPENSE"),
]

# asyncpg binds parameters with their declared type, so the "type" column must be
# declared as the actual category_type enum here (create_type=False - it already exists) -
# a plain sa.String column silently fails to cast the bound VARCHAR to the enum at insert time.
categories_table = sa.table(
    "categories",
    sa.column("name", sa.String),
    sa.column("type", PGEnum("INCOME", "EXPENSE", name="category_type", create_type=False)),
    sa.column("is_system", sa.Boolean),
    sa.column("is_archived", sa.Boolean),
)


def upgrade() -> None:
    op.bulk_insert(
        categories_table,
        [
            {"name": name, "type": category_type, "is_system": True, "is_archived": False}
            for name, category_type in _SYSTEM_CATEGORIES
        ],
    )


def downgrade() -> None:
    names = [name for name, _ in _SYSTEM_CATEGORIES]
    stmt = sa.text("DELETE FROM categories WHERE is_system = true AND name IN :names").bindparams(
        sa.bindparam("names", expanding=True)
    )
    op.get_bind().execute(stmt, {"names": names})
