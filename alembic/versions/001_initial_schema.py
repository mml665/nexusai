"""Baseline schema — matches scripts/init_db.sql

This migration creates the full NexusAI schema. If the database was already
initialized by init_db.sql (Docker entrypoint), run:

    alembic stamp head

to mark this migration as applied without executing it.

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ── TimescaleDB hypertables ──
    op.create_table(
        "sensor_readings",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_id", sa.Text, nullable=False),
        sa.Column("sensor_type", sa.Text, nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("status", sa.Text, server_default="normal"),
    )
    op.execute("SELECT create_hypertable('sensor_readings', 'time', if_not_exists => TRUE)")
    op.create_index("idx_sensor_device", "sensor_readings", ["device_id", sa.text("time DESC")])
    op.create_index("idx_sensor_type", "sensor_readings", ["sensor_type", sa.text("time DESC")])

    op.create_table(
        "oee_metrics",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_id", sa.Text, nullable=False),
        sa.Column("availability", sa.Float),
        sa.Column("performance", sa.Float),
        sa.Column("quality", sa.Float),
        sa.Column("oee", sa.Float),
        sa.Column("output_count", sa.Integer, server_default="0"),
        sa.Column("defect_count", sa.Integer, server_default="0"),
    )
    op.execute("SELECT create_hypertable('oee_metrics', 'time', if_not_exists => TRUE)")
    op.create_index("idx_oee_device", "oee_metrics", ["device_id", sa.text("time DESC")])

    # ── Business tables ──
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("device_id", sa.Text, unique=True, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("line", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("sensors", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column("status", sa.Text, server_default="running"),
        sa.Column("installed_at", sa.Date, server_default=sa.text("CURRENT_DATE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "maintenance_predictions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("device_id", sa.Text, nullable=False),
        sa.Column("health_score", sa.Integer, nullable=False),
        sa.Column("predicted_rul", sa.Integer),
        sa.Column("risk_level", sa.Text, nullable=False),
        sa.Column("recommendation", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "diagnosis_reports",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("device_id", sa.Text, nullable=False),
        sa.Column("anomaly_type", sa.Text, nullable=False),
        sa.Column("sensor_data", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column("diagnosis", sa.Text, nullable=False),
        sa.Column("recommendation", sa.Text, nullable=False),
        sa.Column("urgency", sa.Text, nullable=False),
        sa.Column("rag_sources", sa.dialects.postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("device_id", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("status", sa.Text, server_default="triggered"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "work_orders",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("device_id", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("priority", sa.Text, server_default="medium"),
        sa.Column("status", sa.Text, server_default="open"),
        sa.Column("description", sa.Text),
        sa.Column("assigned_to", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("username", sa.Text, unique=True, nullable=False),
        sa.Column("password", sa.Text, nullable=False),
        sa.Column("role", sa.Text, server_default="viewer"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("resource", sa.Text, nullable=False),
        sa.Column("detail", sa.dialects.postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # ── pgvector knowledge base ──
    op.create_table(
        "knowledge_base",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("device_type", sa.Text),
        sa.Column("embedding", sa.dialects.postgresql.ARRAY(sa.Float)),
    )
    op.execute(
        "ALTER TABLE knowledge_base ALTER COLUMN embedding TYPE vector(1024) USING embedding::vector(1024)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_kb_embedding ON knowledge_base USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    # ── Seed data ──
    op.execute("""
        INSERT INTO users (username, password, role) VALUES
            ('admin', crypt('admin123', gen_salt('bf', 12)), 'admin'),
            ('operator', crypt('operator123', gen_salt('bf', 12)), 'operator'),
            ('viewer', crypt('viewer123', gen_salt('bf', 12)), 'viewer')
        ON CONFLICT (username) DO NOTHING
    """)

    op.execute("""
        INSERT INTO devices (device_id, name, line, type, sensors) VALUES
            ('CNC-A01', 'CNC加工中心A01', 'A', 'CNC', '["temperature","vibration","spindle_speed","cutting_force"]'),
            ('CNC-A02', 'CNC加工中心A02', 'A', 'CNC', '["temperature","vibration","spindle_speed","cutting_force"]'),
            ('ROBOT-A01', '机械臂A01', 'A', 'Robot', '["temperature","vibration","current","position_accuracy"]'),
            ('PRESS-B01', '液压机B01', 'B', 'Press', '["temperature","hydraulic_pressure","pressure","stroke"]'),
            ('PRESS-B02', '液压机B02', 'B', 'Press', '["temperature","hydraulic_pressure","pressure","stroke"]'),
            ('CONV-B01', '传送带B01', 'B', 'Conveyor', '["temperature","rpm","current","speed"]'),
            ('OVEN-C01', '工业炉C01', 'C', 'Oven', '["temperature","gas_flow","pressure","door_status"]'),
            ('COOLER-C01', '冷却器C01', 'C', 'Cooler', '["temperature","flow_rate","pressure","valve_position"]'),
            ('ROBOT-C01', '机械臂C01', 'C', 'Robot', '["temperature","vibration","current","position_accuracy"]')
        ON CONFLICT (device_id) DO NOTHING
    """)


def downgrade() -> None:
    op.drop_table("knowledge_base")
    op.drop_table("audit_logs")
    op.drop_table("users")
    op.drop_table("work_orders")
    op.drop_table("alerts")
    op.drop_table("diagnosis_reports")
    op.drop_table("maintenance_predictions")
    op.drop_table("devices")
    op.drop_table("oee_metrics")
    op.drop_table("sensor_readings")
