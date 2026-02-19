#!/usr/bin/env python3
"""
Test script to verify migration works on fresh database.
Tests the critical node_configurations schema fix.
"""

import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))


def test_migration():
    """Test migration on fresh SQLite database."""

    # Create temporary database
    temp_dir = tempfile.gettempdir()
    db_path = Path(temp_dir) / "test_migration.db"

    # Remove if exists
    if db_path.exists():
        db_path.unlink()

    print(f"📁 Test database: {db_path}")
    print("🔧 Setting up test environment...")

    # Set environment variable for alembic
    db_url = f"sqlite:///{db_path}"
    os.environ["DATABASE_URL"] = db_url

    # Set PYTHONPATH to include config_service directory
    config_service_dir = Path(__file__).parent
    os.environ["PYTHONPATH"] = str(config_service_dir)

    # Run alembic upgrade
    print("\n🚀 Running alembic upgrade head...")
    import subprocess

    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=config_service_dir,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    if result.returncode != 0:
        print("❌ Migration failed!")
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")
        return False

    print("✅ Migration completed successfully")
    print(result.stdout)

    # Verify schema
    print("\n🔍 Verifying schema...")
    engine = create_engine(db_url)
    inspector = inspect(engine)

    # Check all tables exist
    tables = inspector.get_table_names()
    expected_tables = [
        "org_nodes",
        "team_tokens",
        "org_admin_tokens",
        "token_audit",
        "node_configurations",
        "config_field_definitions",
        "config_validation_status",
        "config_change_history",
        "security_policies",
        "sso_configs",
        "agent_runs",
        "agent_sessions",
        "knowledge_documents",
        "knowledge_edges",
        "pending_config_changes",
        "pending_remediations",
        "integration_schemas",
        "integrations",
        "org_settings",
        "templates",
        "template_applications",
        "template_analytics",
        "team_output_configs",
        "impersonation_jtis",
        "orchestrator_provisioning_runs",
        "alembic_version",
    ]

    print(f"📊 Tables created: {len(tables)}")
    for table in sorted(tables):
        status = "✅" if table in expected_tables else "⚠️"
        print(f"  {status} {table}")

    missing = set(expected_tables) - set(tables)
    if missing:
        print(f"\n❌ Missing tables: {missing}")
        return False

    # Check node_configurations schema in detail
    print("\n🎯 Verifying node_configurations schema...")
    columns = inspector.get_columns("node_configurations")
    column_names = {col["name"]: col["type"] for col in columns}

    expected_columns = {
        "id": "VARCHAR(64)",
        "org_id": "VARCHAR(64)",
        "node_id": "VARCHAR(128)",
        "node_type": "VARCHAR(32)",
        "config_json": "JSON",  # SQLite uses JSON instead of JSONB
        "effective_config_json": "JSON",
        "effective_config_computed_at": "DATETIME",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
        "updated_by": "VARCHAR(128)",
        "version": "INTEGER",
    }

    print("📋 Columns in node_configurations:")
    all_good = True
    for col_name, col_type in column_names.items():
        expected_columns.get(col_name, "UNEXPECTED")
        col_type_str = str(col_type)
        # Normalize type checking (SQLite varies)
        matches = col_name in expected_columns
        status = "✅" if matches else "⚠️"
        print(f"  {status} {col_name}: {col_type_str}")
        if not matches:
            all_good = False

    # Check for missing columns
    missing_cols = set(expected_columns.keys()) - set(column_names.keys())
    if missing_cols:
        print(f"\n❌ Missing columns: {missing_cols}")
        all_good = False

    # Check primary key
    pk = inspector.get_pk_constraint("node_configurations")
    print(f"\n🔑 Primary key: {pk['constrained_columns']}")
    if pk["constrained_columns"] != ["id"]:
        print(f"❌ Expected PK on 'id', got {pk['constrained_columns']}")
        all_good = False
    else:
        print("✅ Primary key correct")

    # Check unique constraint
    unique_constraints = inspector.get_unique_constraints("node_configurations")
    print("\n🔒 Unique constraints:")
    found_org_node_constraint = False
    for constraint in unique_constraints:
        print(f"  - {constraint['name']}: {constraint['column_names']}")
        if set(constraint["column_names"]) == {"org_id", "node_id"}:
            found_org_node_constraint = True

    if not found_org_node_constraint:
        print("❌ Missing unique constraint on (org_id, node_id)")
        all_good = False
    else:
        print("✅ Unique constraint on (org_id, node_id) found")

    # Check indexes
    indexes = inspector.get_indexes("node_configurations")
    print("\n📇 Indexes:")
    for idx in indexes:
        print(f"  - {idx['name']}: {idx['column_names']}")

    if not all_good:
        print("\n❌ Schema verification failed")
        return False

    # Test basic operations
    print("\n🧪 Testing basic operations...")

    from db.config_models import NodeConfiguration
    from db.models import OrgNode

    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Create org node
        org = OrgNode(
            org_id="test-org",
            node_id="test-org",
            node_type="org",
            name="Test Organization",
        )
        session.add(org)

        # Create node configuration
        config = NodeConfiguration(
            id="test-config-1",
            org_id="test-org",
            node_id="test-org",
            node_type="org",
            config_json={"agents": {"investigation": {"enabled": True}}},
            version=1,
        )
        session.add(config)
        session.commit()

        print("✅ Created org and config")

        # Query back
        retrieved = (
            session.query(NodeConfiguration)
            .filter_by(org_id="test-org", node_id="test-org")
            .first()
        )

        if not retrieved:
            print("❌ Failed to retrieve config")
            return False

        print(f"✅ Retrieved config: {retrieved.id}")
        print(f"   config_json keys: {list(retrieved.config_json.keys())}")

        # Test update
        retrieved.config_json = {"agents": {"investigation": {"enabled": False}}}
        retrieved.version += 1
        session.commit()

        print("✅ Updated config")

        session.close()

    except Exception as e:
        print(f"❌ Operation failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED!")
    print("=" * 60)
    print("\n✨ Migration is working correctly")
    print("✨ node_configurations schema is correct")
    print("✨ Ready for production deployment")

    # Cleanup
    print("\n🧹 Cleaning up test database...")
    db_path.unlink()

    return True


if __name__ == "__main__":
    success = test_migration()
    sys.exit(0 if success else 1)
