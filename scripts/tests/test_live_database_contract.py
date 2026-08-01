"""Read-only core contract executed when live database settings are supplied."""

CORE_TABLES = {
    "ENTITIES", "AGENT_REGISTRY", "WORKSPACES", "TASK_PLANS",
    "TASK_STEPS", "SKILL_META", "LOOP_RUNS", "SYSTEM_CONFIG",
}


def test_selected_database_exposes_core_contract(db_type, db_connection):
    with db_connection.cursor() as cursor:
        if db_type == "pg":
            cursor.execute("SELECT version()")
            assert "PostgreSQL" in str(cursor.fetchone()[0])
            cursor.execute(
                "SELECT upper(table_name) FROM information_schema.tables "
                "WHERE table_schema = current_schema()"
            )
        else:
            cursor.execute("SELECT TABLE_NAME FROM USER_TABLES")
        present = {str(row[0]).upper() for row in cursor.fetchall()}
    assert CORE_TABLES <= present
