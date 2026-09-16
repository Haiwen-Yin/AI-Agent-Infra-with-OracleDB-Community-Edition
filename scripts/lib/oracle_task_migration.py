"""Resumable owner-only TASK_STEPS copy/switch; never a platform-wide fence.

The original reference-partition table must be emptied after an independent
backup is verified, otherwise its FK still prevents parent status changes.
DDL is checkpointed but not transactional. After original rows are cleared,
recovery completes the switch forward while task writes remain fenced.
"""
from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager

SOURCE = "TASK_STEPS"
SHADOW = "CX415_TASK_STEPS_NEW"
BACKUP = "CX415_TASK_STEPS_BACKUP"
OLD = "CX415_TASK_STEPS_OLD"
COLS = ("STEP_ID", "PLAN_ID", "PLAN_STATUS", "STEP_ORDER", "DESCRIPTION",
        "TOOL_NAME", "TOOL_INPUT", "TOOL_OUTPUT", "ASSIGNED_AGENT_ID", "LOOP_ID",
        "STEP_COMPLETION_TYPE", "STATUS", "STARTED_AT", "COMPLETED_AT")
DEFS = """STEP_ID VARCHAR2(64) NOT NULL, PLAN_ID VARCHAR2(64) NOT NULL,
 PLAN_STATUS VARCHAR2(30) NOT NULL, STEP_ORDER NUMBER(5) NOT NULL,
 DESCRIPTION VARCHAR2(2000) NOT NULL, TOOL_NAME VARCHAR2(128), TOOL_INPUT JSON,
 TOOL_OUTPUT JSON, ASSIGNED_AGENT_ID VARCHAR2(64), LOOP_ID VARCHAR2(64),
 STEP_COMPLETION_TYPE VARCHAR2(20) DEFAULT 'MANUAL',
 STATUS VARCHAR2(30) DEFAULT 'PENDING' NOT NULL, STARTED_AT TIMESTAMP,
 COMPLETED_AT TIMESTAMP"""


def identifier(value):
    if not re.fullmatch(r"[A-Z][A-Z0-9_$#]{0,127}", value):
        raise ValueError("Unsupported database identifier")
    return '"' + value + '"'


class TaskMigration:
    def __init__(self, conn, mutex_conn, *, checkpoint=None):
        self.conn, self.mutex_conn = conn, mutex_conn
        self.checkpoint = checkpoint or (lambda _: None)
        self.sid = str(self.scalar("SELECT SYS_CONTEXT('USERENV','SESSIONID') FROM DUAL"))
        pdb = self.scalar("SELECT SYS_CONTEXT('USERENV','CON_NAME') FROM DUAL")
        if str(pdb).upper() in {"TEST", "CDB$ROOT", "PDB$SEED"}:
            raise ValueError("Task migration refuses TEST and CDB infrastructure containers")
        if self.scalar("SELECT SYS_CONTEXT('USERENV','SESSION_USER') FROM DUAL") != self.scalar(
                "SELECT SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM DUAL"):
            raise ValueError("Connect as the schema owner")

    def rows(self, sql, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params or {})
            return [tuple(v.read() if hasattr(v, "read") else v for v in row) for row in cur.fetchall()]

    def scalar(self, sql, params=None):
        rows = self.rows(sql, params)
        return rows[0][0] if rows else None

    def execute(self, sql, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params or {})

    def exists(self, table):
        return bool(self.scalar("SELECT COUNT(*) FROM USER_TABLES WHERE TABLE_NAME=:n", {"n": table}))

    def setup(self):
        for name, ddl in (
            ("CX415_TASK_SWITCH", "MIGRATION_KEY VARCHAR2(64) PRIMARY KEY, STATE VARCHAR2(20) NOT NULL, "
             "STAGE VARCHAR2(40) NOT NULL, OWNER_SID VARCHAR2(64), INVENTORY CLOB, "
             "UPDATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, "
             "CONSTRAINT CX415_SWITCH_STATE CHECK (STATE IN ('PREPARING','DUAL_WRITE','CUTOVER','VERIFIED','ROLLBACK'))"),
            ("CX415_TASK_SWITCH_AUDIT", "EVENT_ID NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
             "STAGE VARCHAR2(40) NOT NULL, ACTOR VARCHAR2(128) NOT NULL, SESSION_ID VARCHAR2(64) NOT NULL, "
             "DETAIL CLOB, CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL"),
            ("CX415_TASK_MUTEX", "MIGRATION_KEY VARCHAR2(64) PRIMARY KEY"),
            ("CX415_TASK_DIRTY", "STEP_ID VARCHAR2(64) PRIMARY KEY"),
        ):
            if not self.exists(name):
                self.execute(f"CREATE TABLE {name} ({ddl})")
        for table, columns, values in (
            ("CX415_TASK_MUTEX", "MIGRATION_KEY", "'TASK_STEPS'"),
            ("CX415_TASK_SWITCH", "MIGRATION_KEY,STATE,STAGE", "'TASK_STEPS','PREPARING','NEW'"),
        ):
            self.execute(f"INSERT INTO {table} ({columns}) SELECT {values} FROM DUAL "
                         f"WHERE NOT EXISTS (SELECT 1 FROM {table} WHERE MIGRATION_KEY='TASK_STEPS')")
        self.conn.commit()

    @contextmanager
    def owner_lock(self):
        with self.mutex_conn.cursor() as cur:
            cur.execute("SELECT MIGRATION_KEY FROM CX415_TASK_MUTEX WHERE MIGRATION_KEY='TASK_STEPS' FOR UPDATE NOWAIT")
            try:
                yield
            finally:
                self.mutex_conn.rollback()

    def status(self):
        return self.rows("SELECT STATE,STAGE FROM CX415_TASK_SWITCH WHERE MIGRATION_KEY='TASK_STEPS'")[0]

    def audit(self, stage, detail=None):
        self.execute("INSERT INTO CX415_TASK_SWITCH_AUDIT(STAGE,ACTOR,SESSION_ID,DETAIL) "
                     "VALUES(:s,USER,:sid,:d)", {"s": stage, "sid": self.sid, "d": json.dumps(detail or {}, default=str)})

    def mark(self, state, stage, detail=None):
        self.execute("UPDATE CX415_TASK_SWITCH SET STATE=:s,STAGE=:g,OWNER_SID=:sid," 
                     "UPDATED_AT=CURRENT_TIMESTAMP WHERE MIGRATION_KEY='TASK_STEPS'",
                     {"s": state, "g": stage, "sid": self.sid})
        self.execute("UPDATE CX_TASK_MIGRATION_CONTROL SET STATE=:s,VERSION=VERSION+1,UPDATED_BY=USER,"
                     "REASON=:g,UPDATED_AT=CURRENT_TIMESTAMP WHERE MIGRATION_KEY='TASK_STEPS'", {"s": state, "g": stage})
        self.audit(stage, detail)
        self.conn.commit()
        self.checkpoint(stage)

    def inventory(self):
        columns = self.rows("SELECT COLUMN_NAME FROM USER_TAB_COLUMNS WHERE TABLE_NAME='TASK_STEPS' ORDER BY COLUMN_ID")
        if tuple(r[0] for r in columns) != COLS:
            raise ValueError("TASK_STEPS column layout requires a reviewed migration extension")
        if self.scalar("SELECT COUNT(*) FROM USER_POLICIES WHERE OBJECT_NAME='TASK_STEPS'"):
            raise ValueError("Existing row policies require an explicit policy-preserving migration")
        if self.scalar("SELECT COUNT(*) FROM USER_TRIGGERS WHERE TABLE_NAME='TASK_STEPS' AND TRIGGER_NAME NOT LIKE 'CX415_%'"):
            raise ValueError("Existing business triggers require a reviewed migration extension")
        if self.scalar("SELECT COUNT(*) FROM USER_CONSTRAINTS WHERE TABLE_NAME='TASK_STEPS' AND (STATUS<>'ENABLED' OR VALIDATED<>'VALIDATED')"):
            raise ValueError("Repair disabled or unvalidated source constraints before migration")
        if self.scalar("SELECT COUNT(*) FROM ALL_CONSTRAINTS WHERE CONSTRAINT_TYPE='R' AND R_OWNER=USER AND OWNER<>USER "
                       "AND R_CONSTRAINT_NAME IN (SELECT CONSTRAINT_NAME FROM USER_CONSTRAINTS WHERE TABLE_NAME='TASK_STEPS')"):
            raise ValueError("Cross-schema references require an explicitly coordinated migration")
        known = {"FK_STEP_PLAN", "FK_TS_ASSIGNED_AGENT", "FK_TS_LOOP", "CK_TS_STATUS",
                 "CK_TS_COMPLETION", "PK_TASK_STEPS", "UK_TASK_STEPS_ID"}
        for name, kind, generated in self.rows("SELECT CONSTRAINT_NAME,CONSTRAINT_TYPE,GENERATED FROM USER_CONSTRAINTS WHERE TABLE_NAME='TASK_STEPS'"):
            if name not in known and not (kind == "C" and generated == "GENERATED NAME"):
                raise ValueError("Custom task constraint requires a reviewed migration extension")
        refs = self.rows("SELECT TABLE_NAME,CONSTRAINT_NAME FROM USER_CONSTRAINTS WHERE CONSTRAINT_TYPE='R' "
                         "AND R_CONSTRAINT_NAME IN (SELECT CONSTRAINT_NAME FROM USER_CONSTRAINTS WHERE TABLE_NAME='TASK_STEPS')")
        foreign = []
        for table, name in refs:
            ddl = self.scalar("SELECT DBMS_METADATA.GET_DDL('REF_CONSTRAINT',:n) FROM DUAL", {"n": name})
            foreign.append({"table": table, "name": name, "ddl": ddl.strip().rstrip(';')})
        indexes = []
        for name, kind, unique, partitioned in self.rows("SELECT INDEX_NAME,INDEX_TYPE,UNIQUENESS,PARTITIONED "
                                                       "FROM USER_INDEXES WHERE TABLE_NAME='TASK_STEPS'"):
            if kind == "LOB":
                continue
            if unique == "UNIQUE":
                if name not in {"PK_TASK_STEPS", "UK_TASK_STEPS_ID"}:
                    raise ValueError("Custom unique task index requires a reviewed migration extension")
                continue
            if kind != "NORMAL":
                raise ValueError("Custom task index requires a reviewed migration extension")
            cols = self.rows("SELECT COLUMN_NAME,DESCEND FROM USER_IND_COLUMNS WHERE INDEX_NAME=:n ORDER BY COLUMN_POSITION", {"n": name})
            indexes.append({"columns": cols, "local": partitioned == "YES"})
        guards = sorted({"TASK_PLANS", "TASK_STEPS", "TASK_CONTEXT_SNAPSHOTS"} | {r[0] for r in refs})
        result = {"foreign": foreign, "indexes": indexes, "guards": guards,
                  "grants": self.rows("SELECT GRANTEE,PRIVILEGE,GRANTABLE FROM USER_TAB_PRIVS_MADE WHERE TABLE_NAME='TASK_STEPS'"),
                  "comments": self.rows("SELECT COLUMN_NAME,COMMENTS FROM USER_COL_COMMENTS WHERE TABLE_NAME='TASK_STEPS' AND COMMENTS IS NOT NULL"),
                  "table_comment": self.scalar("SELECT COMMENTS FROM USER_TAB_COMMENTS WHERE TABLE_NAME='TASK_STEPS'"),
                  "dependencies": self.rows("SELECT DISTINCT NAME,TYPE FROM USER_DEPENDENCIES WHERE REFERENCED_NAME='TASK_STEPS'")}
        self.execute("UPDATE CX415_TASK_SWITCH SET INVENTORY=:v WHERE MIGRATION_KEY='TASK_STEPS'", {"v": json.dumps(result)})
        self.conn.commit()
        return result

    def saved_inventory(self):
        data = self.scalar("SELECT INVENTORY FROM CX415_TASK_SWITCH WHERE MIGRATION_KEY='TASK_STEPS'")
        return json.loads(data) if data else self.inventory()

    def guard(self, table, index):
        self.execute(f"""CREATE OR REPLACE TRIGGER CX415_TASK_G{index:02d}
 BEFORE INSERT OR UPDATE OR DELETE ON {identifier(table)}
 DECLARE s VARCHAR2(20); own VARCHAR2(64);
 BEGIN
 SELECT STATE,OWNER_SID INTO s,own FROM CX415_TASK_SWITCH WHERE MIGRATION_KEY='TASK_STEPS';
 IF s <> 'VERIFIED' THEN
   SELECT STATE,OWNER_SID INTO s,own FROM CX415_TASK_SWITCH WHERE MIGRATION_KEY='TASK_STEPS' FOR UPDATE WAIT 5;
   IF s='CUTOVER' AND (own IS NULL OR own<>SYS_CONTEXT('USERENV','SESSIONID')) THEN
     RAISE_APPLICATION_ERROR(-20075,'Task storage migration in progress; retry the task operation');
   END IF;
 END IF;
 END;""")

    def freeze(self, stage):
        self.mark("CUTOVER", stage)
        # Covers transactions that began before the guard triggers existed.
        for table in self.saved_inventory()["guards"]:
            if self.exists(table):
                self.execute(f"LOCK TABLE {identifier(table)} IN EXCLUSIVE MODE NOWAIT")
        self.conn.commit()

    def create_copies(self, inv):
        if not self.exists(SHADOW):
            self.execute(f"""CREATE TABLE {SHADOW} ({DEFS},
 CONSTRAINT CX415_TS_PK PRIMARY KEY(STEP_ID,PLAN_ID),
 CONSTRAINT CX415_TS_UQ UNIQUE(STEP_ID),
 CONSTRAINT CX415_TS_PLAN FOREIGN KEY(PLAN_ID) REFERENCES TASK_PLANS(PLAN_ID),
 CONSTRAINT CX415_TS_AGENT FOREIGN KEY(ASSIGNED_AGENT_ID) REFERENCES AGENT_REGISTRY(AGENT_ID),
 CONSTRAINT CX415_TS_LOOP FOREIGN KEY(LOOP_ID) REFERENCES ENTITIES(ENTITY_ID),
 CONSTRAINT CX415_TS_STATUS CHECK(STATUS IN ('PENDING','RUNNING','BLOCKED','SUCCESS','FAILED','SKIPPED','WAITING_LOOP')),
 CONSTRAINT CX415_TS_COMPLETION CHECK(STEP_COMPLETION_TYPE IN ('MANUAL','LOOP','SPEC')))
 PARTITION BY HASH(PLAN_ID) PARTITIONS 16 ENABLE ROW MOVEMENT""")
        if not self.exists(BACKUP):
            self.execute(f"CREATE TABLE {BACKUP} ({DEFS}, CONSTRAINT CX415_BK_PK PRIMARY KEY(STEP_ID))")
        for i, idx in enumerate(inv["indexes"]):
            name = f"CX415_TS_I{i:02d}"
            if not self.scalar("SELECT COUNT(*) FROM USER_INDEXES WHERE INDEX_NAME=:n", {"n": name}):
                cols = ",".join(identifier(c) + (" DESC" if d == "DESC" else "") for c, d in idx["columns"])
                self.execute(f"CREATE INDEX {name} ON {SHADOW}({cols})" + (" LOCAL" if idx["local"] else ""))

    def install_mirror(self):
        body = []
        for table in (SHADOW, BACKUP):
            updates = ",".join(f"t.{c}=:NEW.{c}" for c in COLS if c != "STEP_ID")
            body.append(f"""IF DELETING OR (UPDATING AND :OLD.STEP_ID<>:NEW.STEP_ID) THEN
 DELETE FROM {table} WHERE STEP_ID=:OLD.STEP_ID; END IF;
 IF NOT DELETING THEN
 MERGE INTO {table} t USING (SELECT :NEW.STEP_ID sid FROM DUAL) s ON(t.STEP_ID=s.sid)
 WHEN MATCHED THEN UPDATE SET {updates}
 WHEN NOT MATCHED THEN INSERT({','.join(COLS)}) VALUES({','.join(':NEW.'+c for c in COLS)});
 END IF;""")
        self.execute(f"""CREATE OR REPLACE TRIGGER CX415_TASK_MIRROR AFTER INSERT OR UPDATE OR DELETE ON TASK_STEPS FOR EACH ROW
 BEGIN
 {''.join(body)}
 IF DELETING OR UPDATING THEN
 MERGE INTO CX415_TASK_DIRTY t USING (SELECT :OLD.STEP_ID sid FROM DUAL) s ON(t.STEP_ID=s.sid)
 WHEN NOT MATCHED THEN INSERT(STEP_ID) VALUES(s.sid);
 END IF;
 END;""")
        errors = self.rows("SELECT NAME,LINE,TEXT FROM USER_ERRORS WHERE NAME LIKE 'CX415_TASK_%' ORDER BY NAME,SEQUENCE")
        if errors:
            raise RuntimeError(str(errors))

    def copy(self):
        # Insert-only initial snapshot cannot overwrite a newer mirrored row.
        # Deletes racing this snapshot are repaired from the transactionally
        # captured dirty-key set before the first consistent verification.
        import oracledb
        with self.conn.cursor() as read, self.conn.cursor() as write:
            read.execute(f"SELECT {','.join(COLS)} FROM TASK_STEPS")
            write.setinputsizes(**{"v6": oracledb.DB_TYPE_JSON, "v7": oracledb.DB_TYPE_JSON})
            for row in read:
                values = {f"v{i}": v for i, v in enumerate(row)}
                for table in (SHADOW, BACKUP):
                    try:
                        write.execute(f"INSERT INTO {table}({','.join(COLS)}) VALUES({','.join(':v'+str(i) for i in range(len(COLS)))})", values)
                    except oracledb.IntegrityError as exc:
                        if getattr(exc.args[0], "code", None) != 1:
                            raise
                self.conn.commit()
        self.mark("PREPARING", "COPIED")

    def reconcile(self):
        # One short task transaction per batch; never freeze the platform or
        # hold a task-wide lock for the duration of the base-table copy.
        while True:
            self.execute("SELECT STATE FROM CX415_TASK_SWITCH WHERE MIGRATION_KEY='TASK_STEPS' FOR UPDATE WAIT 5")
            keys = self.rows("SELECT STEP_ID FROM CX415_TASK_DIRTY FETCH FIRST 100 ROWS ONLY")
            for (key,) in keys:
                for table in (SHADOW, BACKUP):
                    self.execute(f"DELETE FROM {table} WHERE STEP_ID=:k", {"k": key})
                    self.execute(f"INSERT INTO {table} SELECT * FROM TASK_STEPS WHERE STEP_ID=:k", {"k": key})
                self.execute("DELETE FROM CX415_TASK_DIRTY WHERE STEP_ID=:k", {"k": key})
            self.conn.commit()
            if not keys:
                break

    def digest(self, table):
        digest, count = hashlib.sha256(), 0
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT {','.join(COLS)} FROM {identifier(table)} ORDER BY STEP_ID")
            for row in cur:
                encoded = json.dumps(row, sort_keys=True, default=str, ensure_ascii=True, separators=(',', ':')).encode()
                digest.update(len(encoded).to_bytes(8, 'big') + encoded)
                count += 1
        return {"count": count, "sha256": digest.hexdigest()}

    def verify_copy(self):
        self.conn.commit()
        self.execute("SET TRANSACTION READ ONLY")
        try:
            result = {t: self.digest(t) for t in (SOURCE, SHADOW, BACKUP)}
        finally:
            self.conn.rollback()
        if len({(v['count'], v['sha256']) for v in result.values()}) != 1:
            raise ValueError("Task copy differs from source; task storage was not switched")
        return result

    def switch(self, inv):
        self.freeze("SWITCH_FENCED")
        # Mirrored transactions preserve the verified equality until this fence.
        if self.scalar("SELECT COUNT(*) FROM USER_TRIGGERS WHERE TRIGGER_NAME='CX415_TASK_MIRROR'"):
            self.execute("DROP TRIGGER CX415_TASK_MIRROR")
        if self.exists(SHADOW) and not self.exists(OLD):
            self.execute(f"ALTER TABLE TASK_STEPS RENAME TO {OLD}")
        self.mark("CUTOVER", "OLD_RENAMED")
        if self.exists(SHADOW):
            self.execute(f"ALTER TABLE {SHADOW} RENAME TO TASK_STEPS")
        self.mark("CUTOVER", "NEW_RENAMED")
        # Install the same fence on the newly named table before releasing it.
        self.guard(SOURCE, 99)
        for ref in inv["foreign"]:
            current = self.rows("SELECT p.TABLE_NAME FROM USER_CONSTRAINTS f JOIN USER_CONSTRAINTS p "
                                "ON p.CONSTRAINT_NAME=f.R_CONSTRAINT_NAME WHERE f.CONSTRAINT_NAME=:n", {"n": ref["name"]})
            if current and current[0][0] == SOURCE:
                continue
            if current:
                self.execute(f"ALTER TABLE {identifier(ref['table'])} DROP CONSTRAINT {identifier(ref['name'])}")
            self.execute(ref["ddl"])
        for grantee, privilege, grantable in inv["grants"]:
            if privilege not in {"SELECT", "INSERT", "UPDATE", "DELETE", "REFERENCES", "ALTER", "INDEX", "READ", "FLASHBACK", "DEBUG"}:
                raise ValueError("Unexpected source privilege")
            self.execute(f"GRANT {privilege} ON TASK_STEPS TO {identifier(grantee)}" + (" WITH GRANT OPTION" if grantable == "YES" else ""))
        for col, comment in inv["comments"]:
            self.execute(f"COMMENT ON COLUMN TASK_STEPS.{identifier(col)} IS '" + comment.replace("'", "''") + "'")
        if inv["table_comment"]:
            self.execute("COMMENT ON TABLE TASK_STEPS IS '" + inv["table_comment"].replace("'", "''") + "'")
        self.mark("CUTOVER", "DEPENDENCIES_MOVED")
        # An independent backup has no parent FK, so it survives parent changes.
        if self.digest(SOURCE) != self.digest(BACKUP):
            raise ValueError("Independent rollback copy does not match the replacement")
        self.mark("CUTOVER", "BACKUP_VERIFIED", self.digest(BACKUP))
        if self.exists(OLD):
            if not inv.get("source_ddl"):
                inv["source_ddl"] = self.scalar("SELECT DBMS_METADATA.GET_DDL('TABLE',:n) FROM DUAL", {"n": OLD})
                self.execute("UPDATE CX415_TASK_SWITCH SET INVENTORY=:v WHERE MIGRATION_KEY='TASK_STEPS'", {"v": json.dumps(inv)})
                self.conn.commit()
            if self.scalar("SELECT READ_ONLY FROM USER_TABLES WHERE TABLE_NAME=:n", {"n": OLD}) == "YES":
                self.execute(f"ALTER TABLE {OLD} READ WRITE")
            if self.scalar(f"SELECT COUNT(*) FROM {OLD}"):
                self.execute(f"TRUNCATE TABLE {OLD}")
        self.mark("CUTOVER", "OLD_EMPTIED")
        # Even an empty READ ONLY reference child blocks recursive parent
        # partition movement (ORA-12081). Its independent backup and original
        # DDL are durable; remove the obsolete constraint-bearing structure.
        if self.exists(OLD):
            self.execute(f"DROP TABLE {OLD}")
        self.mark("CUTOVER", "OLD_DROPPED")
        for table in (BACKUP,):
            if self.scalar("SELECT READ_ONLY FROM USER_TABLES WHERE TABLE_NAME=:n", {"n": table}) != "YES":
                self.execute(f"ALTER TABLE {table} READ ONLY")
        for name, kind in inv["dependencies"]:
            if kind == "PACKAGE BODY":
                self.execute(f"ALTER PACKAGE {identifier(name)} COMPILE BODY")
            elif kind == "VIEW":
                self.execute(f"ALTER VIEW {identifier(name)} COMPILE")
            else:
                raise ValueError("Dependency requires explicit recompilation support")
        self.verify_structure(inv)
        self.mark("VERIFIED", "VERIFIED", {"backup": self.digest(BACKUP)})

    def verify_structure(self, inv):
        if self.scalar("SELECT PARTITIONING_TYPE FROM USER_PART_TABLES WHERE TABLE_NAME='TASK_STEPS'") != "HASH":
            raise ValueError("Replacement is not hash partitioned")
        if self.scalar("SELECT COUNT(*) FROM USER_CONSTRAINTS WHERE TABLE_NAME='TASK_STEPS' AND (STATUS<>'ENABLED' OR VALIDATED<>'VALIDATED')"):
            raise ValueError("Replacement constraints are not fully validated")
        if self.scalar("SELECT COUNT(*) FROM USER_CONSTRAINTS f JOIN USER_CONSTRAINTS p ON p.CONSTRAINT_NAME=f.R_CONSTRAINT_NAME "
                       "WHERE f.TABLE_NAME='TASK_STEPS' AND f.CONSTRAINT_NAME='CX415_TS_PLAN' "
                       "AND f.STATUS='ENABLED' AND f.VALIDATED='VALIDATED' AND p.TABLE_NAME='TASK_PLANS'") != 1:
            raise ValueError("Stable task parent foreign key is missing")
        for ref in inv["foreign"]:
            if self.scalar("SELECT COUNT(*) FROM USER_CONSTRAINTS f JOIN USER_CONSTRAINTS p ON p.CONSTRAINT_NAME=f.R_CONSTRAINT_NAME "
                           "WHERE f.CONSTRAINT_NAME=:n AND p.TABLE_NAME='TASK_STEPS' AND f.STATUS='ENABLED' AND f.VALIDATED='VALIDATED'", {"n": ref["name"]}) != 1:
                raise ValueError("Dependent foreign key is missing or invalid")
        for name, kind in inv["dependencies"]:
            if self.scalar("SELECT COUNT(*) FROM USER_OBJECTS WHERE OBJECT_NAME=:n AND OBJECT_TYPE=:t AND STATUS='INVALID'", {"n": name, "t": kind}):
                raise ValueError("A task dependency remains invalid")

    def run(self):
        self.setup()
        with self.owner_lock():
            state, stage = self.status()
            inv = self.saved_inventory()
            if state == "VERIFIED":
                if self.exists(OLD):
                    self.switch(inv)
                self.verify_structure(inv)
                return {"state": "VERIFIED", "already_applied": True}
            switched = self.scalar("SELECT PARTITIONING_TYPE FROM USER_PART_TABLES WHERE TABLE_NAME='TASK_STEPS'") == "HASH"
            if self.exists(OLD) or (switched and self.exists(BACKUP)):
                self.switch(inv)
            else:
                self.create_copies(inv)
                for i, table in enumerate(inv["guards"]):
                    self.guard(table, i)
                self.freeze("CAPTURE_FENCED")
                self.install_mirror()
                self.mark("PREPARING", "CAPTURE_READY")
                self.copy()
                self.reconcile()
                verified = self.verify_copy()
                self.mark("DUAL_WRITE", "VALIDATED", verified)
                self.switch(inv)
            return {"state": self.status()[0], "backup_table": BACKUP, "original_ddl": "CX415_TASK_SWITCH.INVENTORY"}
