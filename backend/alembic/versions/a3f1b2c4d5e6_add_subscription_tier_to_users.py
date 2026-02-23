"""add subscription tier to users

Revision ID: a3f1b2c4d5e6
Revises: 7e292ffc7777
Create Date: 2026-02-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f1b2c4d5e6'
down_revision: Union[str, None] = '7e292ffc7777'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('tier', sa.String(20), server_default='free', nullable=True))
        batch_op.add_column(sa.Column('subscription_expires_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('subscription_expires_at')
        batch_op.drop_column('tier')
