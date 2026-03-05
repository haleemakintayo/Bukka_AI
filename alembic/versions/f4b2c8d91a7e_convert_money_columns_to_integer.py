"""Convert money columns to integer naira

Revision ID: f4b2c8d91a7e
Revises: 8e5c1d2a9f44
Create Date: 2026-03-02 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f4b2c8d91a7e"
down_revision: Union[str, Sequence[str], None] = "8e5c1d2a9f44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.alter_column(
            "total_price",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=True,
            postgresql_using="ROUND(total_price)::integer",
        )

    with op.batch_alter_table("menu_items") as batch_op:
        batch_op.alter_column(
            "price",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=True,
            postgresql_using="ROUND(price)::integer",
        )


def downgrade() -> None:
    with op.batch_alter_table("menu_items") as batch_op:
        batch_op.alter_column(
            "price",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=True,
            postgresql_using="price::double precision",
        )

    with op.batch_alter_table("orders") as batch_op:
        batch_op.alter_column(
            "total_price",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=True,
            postgresql_using="total_price::double precision",
        )
