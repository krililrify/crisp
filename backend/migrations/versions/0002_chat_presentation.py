from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("sites", sa.Column("subtitle", sa.Text(), nullable=False, server_default='私密对话'))
    op.add_column("sites", sa.Column("welcome_heading", sa.Text(), nullable=False, server_default='很高兴为您服务'))
    op.add_column("sites", sa.Column("welcome_icon", sa.Text(), nullable=False, server_default='✦'))
    op.add_column("sites", sa.Column("business_hours", sa.Text(), nullable=False, server_default=''))
    op.add_column("sites", sa.Column("problem_prompt", sa.Text(), nullable=False, server_default='请直接说明您的问题，我们会尽快回复您。'))

def downgrade():
    op.drop_column("sites", "problem_prompt")
    op.drop_column("sites", "business_hours")
    op.drop_column("sites", "welcome_icon")
    op.drop_column("sites", "welcome_heading")
    op.drop_column("sites", "subtitle")
