"""add marketing consent evidence (동의 증적 — consent_records + leads/users 상태 컬럼)

Revision ID: f4c1e8a92b37
Revises: b7e2c4f9a801
Create Date: 2026-07-30 00:00:00.000000

아웃바운드(SES·알림톡) 발송의 법적 전제. 정보통신망법 제50조는 광고성 정보 전송의
수신동의 사실을 전송자가 증명하도록 하므로, ① 추가 전용 증적 로그(consent_records)와
② 현재 상태 컬럼(leads/users)을 함께 둔다.

⚠️ 기존 리드·회원 행은 전부 marketing_consent=false 로 시작한다(명시 동의 증적이
없는 연락처에는 광고성 정보를 보내지 않는다). 이 마이그레이션은 추가 전용 —
기존 데이터 변형 없음.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f4c1e8a92b37'
down_revision: Union[str, None] = 'b7e2c4f9a801'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Column 객체는 한 테이블에 바인딩되면 재사용할 수 없다(SQLAlchemy 2.0 에서 copy() 제거).
# 그래서 매번 새 인스턴스를 만드는 팩토리로 정의한다.
_LEAD_CONSENT_COLUMNS = (
    ('privacy_consent', lambda: sa.Column('privacy_consent', sa.Boolean(), server_default=sa.text('false'), nullable=False)),
    ('privacy_consent_at', lambda: sa.Column('privacy_consent_at', sa.DateTime(), nullable=True)),
    ('marketing_consent', lambda: sa.Column('marketing_consent', sa.Boolean(), server_default=sa.text('false'), nullable=False)),
    ('marketing_consent_at', lambda: sa.Column('marketing_consent_at', sa.DateTime(), nullable=True)),
    ('marketing_withdrawn_at', lambda: sa.Column('marketing_withdrawn_at', sa.DateTime(), nullable=True)),
    ('marketing_confirmed_at', lambda: sa.Column('marketing_confirmed_at', sa.DateTime(), nullable=True)),
    ('consent_text_version', lambda: sa.Column('consent_text_version', sa.String(length=30), nullable=True)),
    ('consent_ip', lambda: sa.Column('consent_ip', sa.String(length=45), nullable=True)),
    ('consent_user_agent', lambda: sa.Column('consent_user_agent', sa.String(length=300), nullable=True)),
)

# users 는 개인정보 수집 동의를 가입 약관으로 이미 받으므로 마케팅 상태만 추가
_USER_CONSENT_COLUMNS = tuple(
    (name, factory) for name, factory in _LEAD_CONSENT_COLUMNS if not name.startswith('privacy_')
)


def upgrade() -> None:
    op.create_table(
        'consent_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('subject_type', sa.String(length=10), nullable=False),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=30), nullable=True),
        sa.Column('purpose', sa.String(length=20), nullable=False),
        sa.Column('action', sa.String(length=12), nullable=False),
        sa.Column('channel', sa.String(length=20), nullable=True),
        sa.Column('text_version', sa.String(length=30), nullable=False),
        sa.Column('text_hash', sa.String(length=64), nullable=False),
        sa.Column('source', sa.String(length=40), nullable=False),
        sa.Column('ip', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=300), nullable=True),
        sa.Column('note', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_consent_records_id'), 'consent_records', ['id'], unique=False)
    op.create_index(op.f('ix_consent_records_subject_type'), 'consent_records', ['subject_type'], unique=False)
    op.create_index(op.f('ix_consent_records_subject_id'), 'consent_records', ['subject_id'], unique=False)
    op.create_index(op.f('ix_consent_records_email'), 'consent_records', ['email'], unique=False)
    op.create_index(op.f('ix_consent_records_created_at'), 'consent_records', ['created_at'], unique=False)

    for _name, factory in _LEAD_CONSENT_COLUMNS:
        op.add_column('leads', factory())
    for _name, factory in _USER_CONSENT_COLUMNS:
        op.add_column('users', factory())


def downgrade() -> None:
    for name, _factory in reversed(_USER_CONSENT_COLUMNS):
        op.drop_column('users', name)
    for name, _factory in reversed(_LEAD_CONSENT_COLUMNS):
        op.drop_column('leads', name)

    op.drop_index(op.f('ix_consent_records_created_at'), table_name='consent_records')
    op.drop_index(op.f('ix_consent_records_email'), table_name='consent_records')
    op.drop_index(op.f('ix_consent_records_subject_id'), table_name='consent_records')
    op.drop_index(op.f('ix_consent_records_subject_type'), table_name='consent_records')
    op.drop_index(op.f('ix_consent_records_id'), table_name='consent_records')
    op.drop_table('consent_records')
