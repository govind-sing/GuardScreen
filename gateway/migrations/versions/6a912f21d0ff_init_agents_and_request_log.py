"""init agents and request_log

Revision ID: 6a912f21d0ff
Revises: 
Create Date: 2026-08-15 17:47:02.886595

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6a912f21d0ff'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('agents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('api_key_hash', sa.String(), nullable=False),
    sa.Column('role', sa.String(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('request_log',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('idempotency_key', sa.String(), nullable=True),
    sa.Column('candidate_id', sa.UUID(), nullable=True),
    sa.Column('model_used', sa.String(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('token_count', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('error_detail', sa.String(), nullable=True),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_request_log_agent_id', 'request_log', ['agent_id'])
    op.create_index('ix_request_log_idempotency_key', 'request_log', ['idempotency_key'])


def downgrade() -> None:
    op.drop_index('ix_request_log_idempotency_key', table_name='request_log')
    op.drop_index('ix_request_log_agent_id', table_name='request_log')
    op.drop_table('request_log')
    op.drop_table('agents')