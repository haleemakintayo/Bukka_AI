"""Add stock tracking columns and stock movements table

Revision ID: 2a1d9e7c6b34
Revises: f4b2c8d91a7e
Create Date: 2026-03-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2a1d9e7c6b34"
down_revision: Union[str, Sequence[str], None] = "f4b2c8d91a7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("menu_items", sa.Column("stock_qty", sa.Integer(), nullable=True))
    op.add_column("menu_items", sa.Column("reorder_level", sa.Integer(), nullable=True))

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("movement_type", sa.String(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("actor_platform", sa.String(), nullable=True),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("timestamp", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["menu_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_stock_movements_id"), "stock_movements", ["id"], unique=False)
    op.create_index(op.f("ix_stock_movements_item_id"), "stock_movements", ["item_id"], unique=False)
    op.create_index(op.f("ix_stock_movements_timestamp"), "stock_movements", ["timestamp"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_stock_movements_timestamp"), table_name="stock_movements")
    op.drop_index(op.f("ix_stock_movements_item_id"), table_name="stock_movements")
    op.drop_index(op.f("ix_stock_movements_id"), table_name="stock_movements")
    op.drop_table("stock_movements")

    op.drop_column("menu_items", "reorder_level")
    op.drop_column("menu_items", "stock_qty")
