"""actual execution artifacts metrics

Revision ID: a4d80d49ae32
Revises: b03b320a103c
Create Date: 2026-09-18 02:30:38.033630

Phase 8B-2 (researchos.execution): adds one new table (`metrics`) and
extends two Phase 8B-1 tables (`artifact_metadata`, `environment_snapshots`)
with columns Phase 8B-1 did not yet need. `Run`/`Experiment`/
`ExperimentSpecification`/`DatasetVersion` and every other pre-existing
table are completely untouched.

Populated-database safety (this phase's own equivalent of the gap
Phase 6/7 had to fix): `artifact_metadata.logical_name` is a new
`NOT NULL` column on a table that may already contain rows from Phase
8B-1 (real `STDOUT`/`STDERR` artifact rows a populated database could
already have). Unlike Phase 6/7's fix, a single literal
`server_default` cannot be used here, because the new column also
carries a `UniqueConstraint(run_id, logical_name)` — two pre-existing
rows for the same `run_id` (one `STDOUT`, one `STDERR`) backfilled to
the same literal default would collide. Instead: the column is added
nullable, backfilled per-row via `UPDATE ... SET logical_name =
LOWER(artifact_type)` (deterministic, and guaranteed non-colliding for
every row Phase 8B-1 could actually have produced, since it never
created two artifacts of the same `artifact_type` for one `Run`), then
altered to `NOT NULL`, and only then does the unique constraint get
added. New rows always require an explicit `logical_name` at the ORM
layer (no Python-side default) from this point on.

`artifact_metadata.artifact_type`'s existing CHECK constraint is
widened by hand below (autogenerate does not detect CHECK-constraint
*value-set* changes on an already-existing enum column — the same gap
noted in every prior phase's migration) to rename Phase 8B-1's unused
`RESULT` member to `RESULT_MANIFEST` and add `METRIC_REPORT`. Renaming
(rather than keeping `RESULT` alongside a new `RESULT_MANIFEST`) is
safe here specifically because no code anywhere in the codebase ever
set `artifact_type='RESULT'` (verified by search before writing this
migration) — Phase 8B-1 only ever created `STDOUT`/`STDERR` rows, so no
existing row anywhere can hold the value being removed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4d80d49ae32'
down_revision: Union[str, None] = 'b03b320a103c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD_ARTIFACT_TYPES = ('STDOUT', 'STDERR', 'CHECKPOINT', 'MODEL', 'PLOT', 'LOG', 'RESULT', 'OTHER')
_NEW_ARTIFACT_TYPES = ('STDOUT', 'STDERR', 'CHECKPOINT', 'MODEL', 'PLOT', 'LOG', 'METRIC_REPORT', 'RESULT_MANIFEST', 'OTHER')


def upgrade() -> None:
    op.create_table('metrics',
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('value_type', sa.Enum('INTEGER', 'FLOAT', name='metricvaluetype', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('unit', sa.String(length=100), nullable=True),
    sa.Column('split', sa.String(length=100), nullable=True),
    sa.Column('aggregation', sa.String(length=100), nullable=True),
    sa.Column('threshold', sa.Float(), nullable=True),
    sa.Column('evaluation_protocol', sa.String(length=500), nullable=True),
    sa.Column('source', sa.String(length=200), nullable=True),
    sa.Column('source_artifact_id', sa.Integer(), nullable=True),
    sa.Column('metadata', sa.JSON(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['research_projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_artifact_id'], ['artifact_metadata.id'], name='fk_metrics_source_artifact_id', ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('metrics', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_metrics_name'), ['name'], unique=False)
        batch_op.create_index(batch_op.f('ix_metrics_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_metrics_run_id'), ['run_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_metrics_source_artifact_id'), ['source_artifact_id'], unique=False)

    # artifact_metadata: add new columns (logical_name nullable for now
    # — see module docstring), backfill, then enforce NOT NULL + the
    # unique constraint.
    with op.batch_alter_table('artifact_metadata', schema=None) as batch_op:
        batch_op.add_column(sa.Column('logical_name', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('source', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('description', sa.Text(), nullable=True))

    op.execute("UPDATE artifact_metadata SET logical_name = LOWER(artifact_type) WHERE logical_name IS NULL")

    with op.batch_alter_table('artifact_metadata', schema=None) as batch_op:
        batch_op.alter_column('logical_name', existing_type=sa.String(length=500), nullable=False)
        batch_op.create_unique_constraint('uq_artifact_metadata_run_logical_name', ['run_id', 'logical_name'])
        batch_op.drop_constraint('artifacttype', type_='check')
        batch_op.alter_column(
            'artifact_type',
            existing_type=sa.Enum(*_OLD_ARTIFACT_TYPES, name='artifacttype', native_enum=False, length=32),
            type_=sa.Enum(*_NEW_ARTIFACT_TYPES, name='artifacttype', native_enum=False, create_constraint=True, length=32),
            existing_nullable=False,
        )

    with op.batch_alter_table('environment_snapshots', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cpu_model', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('cpu_count', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('total_memory_bytes', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('researchos_version', sa.String(length=50), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('environment_snapshots', schema=None) as batch_op:
        batch_op.drop_column('researchos_version')
        batch_op.drop_column('total_memory_bytes')
        batch_op.drop_column('cpu_count')
        batch_op.drop_column('cpu_model')

    with op.batch_alter_table('artifact_metadata', schema=None) as batch_op:
        batch_op.drop_constraint('artifacttype', type_='check')
        batch_op.alter_column(
            'artifact_type',
            existing_type=sa.Enum(*_NEW_ARTIFACT_TYPES, name='artifacttype', native_enum=False, length=32),
            type_=sa.Enum(*_OLD_ARTIFACT_TYPES, name='artifacttype', native_enum=False, create_constraint=True, length=32),
            existing_nullable=False,
        )
        batch_op.drop_constraint('uq_artifact_metadata_run_logical_name', type_='unique')
        batch_op.drop_column('description')
        batch_op.drop_column('source')
        batch_op.drop_column('logical_name')

    with op.batch_alter_table('metrics', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_metrics_source_artifact_id'))
        batch_op.drop_index(batch_op.f('ix_metrics_run_id'))
        batch_op.drop_index(batch_op.f('ix_metrics_project_id'))
        batch_op.drop_index(batch_op.f('ix_metrics_name'))

    op.drop_table('metrics')
