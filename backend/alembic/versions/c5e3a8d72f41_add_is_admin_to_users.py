"""add is_admin to users

Revision ID: c5e3a8d72f41
Revises: b4f2e8c91d23
Create Date: 2026-05-28 11:00:00.000000

운영자 권한 컬럼 추가 — `require_admin` 의존성에서 사용.

운영 배포 후 1회:
    UPDATE users SET is_admin = true WHERE email = 'hosicompany@gmail.com';

또는 `backend/scripts/promote_admin.py --email hosicompany@gmail.com` (idempotent).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5e3a8d72f41'
down_revision: Union[str, None] = 'b4f2e8c91d23'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(
            sa.Column(
                'is_admin',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('is_admin')
