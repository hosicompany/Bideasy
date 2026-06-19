"""widen billing_key columns for at-rest encryption

Revision ID: a3c7e1f9b204
Revises: f2d9a1c84b56
Create Date: 2026-06-19 01:00:00.000000

빌링키 at-rest 암호화(Fernet) 시 암호문이 평문보다 길어지므로 컬럼 폭을 확장.
(평문 저장도 그대로 호환 — 길이만 늘림)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3c7e1f9b204'
down_revision: Union[str, None] = 'f2d9a1c84b56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('users', 'billing_key', type_=sa.String(length=500), existing_nullable=True)
    op.alter_column('users', 'billing_customer_key', type_=sa.String(length=500), existing_nullable=True)


def downgrade() -> None:
    op.alter_column('users', 'billing_key', type_=sa.String(length=200), existing_nullable=True)
    op.alter_column('users', 'billing_customer_key', type_=sa.String(length=100), existing_nullable=True)
