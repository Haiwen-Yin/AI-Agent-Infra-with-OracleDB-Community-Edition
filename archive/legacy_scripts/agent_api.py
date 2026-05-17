"""
Oracle Memory System v0.4.2 - Multi-Agent Architecture Python API
==================================================================
Description: High-level Python API for multi-agent memory management
Version: 1.0
Author: Haiwen Yin (胖头鱼 🐟)
Date: 2026-05-07

Features:
- Agent registration and discovery
- Memory visibility control (SHARED/PRIVATE/COLLABORATIVE)
- Session management with context preservation
- Access audit logging
- Collaboration request handling
"""

import json
import subprocess
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any


# ============================================================================
# Configuration Constants
# ============================================================================

class Config:
    """Configuration for Oracle Memory System Multi-Agent API"""
    
    # SQLcl connection settings
    SQLCL_PATH = "/root/sqlcl/bin/sql"
    DB_USERNAME = "openclaw"
    DB_PASSWORD = "hermes"
    DB_CONNECTION = "//10.10.10.130:1521/openclaw"
    
    # Session timeout (hours)
    SESSION_TIMEOUT_HOURS = 24
    
    # Visibility levels
    VISIBILITY_SHARED = "SHARED"
    VISIBILITY_PRIVATE = "PRIVATE"
    VISIBILITY_COLLABORATIVE = "COLLABORATIVE"


# ============================================================================
# Database Connection Helper
# ============================================================================

def run_sql_command(conn_string: str, sql_query: str) -> Dict[str, Any]:
    """Execute SQL query using SQLcl and return output."""
    cmd = f"{Config.SQLCL_PATH} {conn_string} << 'EOF'\n{sql_query}\nEXIT;"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    return {'output': result.stdout + result.stderr, 'returncode': result.returncode}


def execute_dml(query: str, params: Optional[Dict] = None) -> Dict[str, Any]:
    """Execute DML statement and return result."""
    conn = f"{Config.DB_USERNAME}/{Config.DB_PASSWORD}@{Config.DB_CONNECTION}"
    
    # Bind variables if provided
    if params:
        for key, value in params.items():
            query = query.replace(key, str(value))
    
    return run_sql_command(conn, query)


def execute_query(query: str) -> List[Dict]:
    """Execute SELECT query and return results as list of dictionaries."""
    conn = f"{Config.DB_USERNAME}/{Config.DB_PASSWORD}@{Config.DB_CONNECTION}"
    result = run_sql_command(conn, query)
    
    # Parse output into structured format (simplified - actual parsing depends on SQLcl output format)
    lines = result['output'].strip().split('\n')
    if len(lines) < 2:
        return []
    
    headers = [h.strip() for h in lines[0].split('|') if h.strip()]
    rows = []
    
    for line in lines[1:]:
        if not line.strip() or '-----' in line:
            continue
        values = [v.strip() for v in line.split('|') if v.strip()]
        if len(values) == len(headers):
            row = dict(zip(headers, values))
            rows.append(row)
    
    return rows


# ============================================================================
# Agent Registry API
# ============================================================================

class AgentRegistryAPI:
    """API for agent registration and discovery"""
    
    @staticmethod
    def register_agent(agent_id: str, agent_name: str, agent_type: str = "general", 
                      capabilities: Optional[List[str]] = None,
                      description: str = "", permission_level: str = "READ_WRITE") -> bool:
        """Register a new agent in the registry."""
        
        # Convert capabilities list to JSON string
        cap_json = json.dumps(capabilities) if capabilities else '[]'
        
        sql = f"""
        INSERT INTO agent_registry (AGENT_ID, AGENT_NAME, AGENT_TYPE, DESCRIPTION, 
                                   CAPABILITIES, STATUS, PERMISSION_LEVEL, CREATED_AT)
        VALUES ('{agent_id}', '{agent_name}', '{agent_type}', '{description}',
                '{cap_json}', 'ACTIVE', '{permission_level}', SYSTIMESTAMP)
        """
        
        result = execute_dml(sql)
        return result['returncode'] == 0
    
    @staticmethod
    def get_agent(agent_id: str) -> Optional[Dict]:
        """Retrieve agent information by ID."""
        sql = f"SELECT * FROM v_agent_capabilities WHERE AGENT_ID = '{agent_id}'"
        results = execute_query(sql)
        
        if not results:
            return None
        
        # Parse JSON capabilities back to list
        agent = results[0]
        if 'CAPABILITIES' in agent and isinstance(agent['CAPABILITIES'], str):
            try:
                agent['CAPABILITIES'] = json.loads(agent['CAPABILITIES'])
            except:
                pass
        
        return agent
    
    @staticmethod
    def find_agents_by_type(agent_type: str) -> List[Dict]:
        """Find all agents of a specific type."""
        sql = f"SELECT * FROM v_agent_capabilities WHERE AGENT_TYPE = '{agent_type}'"
        results = execute_query(sql)
        
        for agent in results:
            if 'CAPABILITIES' in agent and isinstance(agent['CAPABILITIES'], str):
                try:
                    agent['CAPABILITIES'] = json.loads(agent['CAPABILITIES'])
                except:
                    pass
        
        return results
    
    @staticmethod
    def find_agents_by_capability(capability: str) -> List[Dict]:
        """Find all agents that have a specific capability."""
        sql = f"""SELECT * FROM v_agent_capabilities 
                  WHERE CAPABILITIES LIKE '%{capability}%'"""
        results = execute_query(sql)
        
        for agent in results:
            if 'CAPABILITIES' in agent and isinstance(agent['CAPABILITIES'], str):
                try:
                    agent['CAPABILITIES'] = json.loads(agent['CAPABILITIES'])
                except:
                    pass
        
        return results


# ============================================================================
# Memory Visibility API
# ============================================================================

class MemoryVisibilityAPI:
    """API for memory visibility and access control"""
    
    @staticmethod
    def create_memory(memory_data: Dict, agent_id: str = None, 
                     visibility: str = "SHARED", accessible_to: Optional[List[str]] = None) -> int:
        """Create a new memory with visibility settings. Returns memory ID."""
        
        # Set visibility defaults based on owner
        if not agent_id and visibility == "PRIVATE":
            visibility = "SHARED"
        
        # Convert accessible_to to JSON string
        accessible_json = json.dumps(accessible_to) if accessible_to else '[]'
        
        # Escape single quotes in memory data for SQL safety
        content = str(memory_data.get('content', '')).replace("'", "''")
        tags = json.dumps(str(memory_data.get('tags', []))).replace("'", "''")
        
        sql = f"""
        INSERT INTO memories (CONTENT, MEMORY_TYPE, CATEGORY, PRIORITY, CREATED_AT, 
                             UPDATED_AT, EXPIRES_AT, TAGS, METADATA, 
                             OWNED_BY_AGENT, VISIBILITY, ACCESSIBLE_TO)
        VALUES ('{content}', 'TEXT', '{memory_data.get('category', 'general')}', 
                {memory_data.get('priority', 2)}, SYSTIMESTAMP, SYSTIMESTAMP, NULL,
                '{tags}', '{}', '{agent_id}', '{visibility}', '{accessible_json}')
        RETURNING ID INTO :mem_id
        """
        
        # Note: Oracle bind variables need different syntax - simplified version here
        sql = f"""
        INSERT INTO memories (CONTENT, MEMORY_TYPE, CATEGORY, PRIORITY, CREATED_AT, 
                             UPDATED_AT, EXPIRES_AT, TAGS, METADATA, 
                             OWNED_BY_AGENT, VISIBILITY, ACCESSIBLE_TO)
        VALUES ('{content}', 'TEXT', '{memory_data.get('category', 'general')}', 
                {memory_data.get('priority', 2)}, SYSTIMESTAMP, SYSTIMESTAMP, NULL,
                '{tags}', '{{}}', '{agent_id}', '{visibility}', '{accessible_json}')
        """
        
        result = execute_dml(sql)
        
        # For simplicity, we'd need to query the last inserted row
        if 'inserted' in str(result.get('output', '')):
            sql_select = "SELECT MAX(ID) FROM memories"
            mem_result = execute_query(sql_select)
            return int(mem_result[0]['MAX(ID)']) if mem_result else -1
        
        return -1
    
    @staticmethod
    def get_agent_memories(agent_id: str) -> List[Dict]:
        """Get all memories accessible to an agent (SHARED + PRIVATE + COLLABORATIVE)."""
        
        sql = f"""
        SELECT m.ID as memory_id, m.VISIBILITY, m.OWNED_BY_AGENT, 
               m.CREATED_AT, m.CONTENT
        FROM memories m
        WHERE 
            -- SHARED: visible to everyone
            (m.VISIBILITY = 'SHARED') OR
            -- PRIVATE: only owner can see  
            (m.VISIBILITY = 'PRIVATE' AND m.OWNED_BY_AGENT = '{agent_id}') OR
            -- COLLABORATIVE: in ACCESSIBLE_TO JSON array
            (m.VISIBILITY = 'COLLABORATIVE' 
             AND EXISTS (
                 SELECT 1 FROM TABLE(
                     JSON_TABLE(m.ACCESSIBLE_TO, '$[*]' COLUMNS(value VARCHAR2(64) PATH '$'))
                 ) t
                 WHERE t.value = '{agent_id}'
             ))
        ORDER BY m.CREATED_AT DESC
        """
        
        return execute_query(sql)
    
    @staticmethod
    def get_private_memories(agent_id: str) -> List[Dict]:
        """Get only the agent's private memories."""
        sql = f"""SELECT ID as memory_id, VISIBILITY, OWNED_BY_AGENT, CREATED_AT, CONTENT
                  FROM memories 
                  WHERE OWNED_BY_AGENT = '{agent_id}' AND VISIBILITY = 'PRIVATE'
                  ORDER BY CREATED_AT DESC"""
        return execute_query(sql)


# ============================================================================
# Session Management API
# ============================================================================

class AgentSessionAPI:
    """API for agent session management with context preservation"""
    
    @staticmethod
    def create_session(agent_id: str, working_memory_id: int = None) -> str:
        """Create a new session. Returns session ID."""
        
        import uuid
        session_id = f"session-{agent_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Escape content for SQL safety
        context_snapshot = '{}'  # Empty initial context
        
        sql = f"""
        INSERT INTO agent_session (SESSION_ID, AGENT_ID, START_TIME, IS_ACTIVE, 
                                  CONTEXT_SNAPSHOT, WORKING_MEMORY_ID)
        VALUES ('{session_id}', '{agent_id}', SYSTIMESTAMP, 'Y', 
                '{context_snapshot}', {working_memory_id})
        """
        
        result = execute_dml(sql)
        return session_id if result['returncode'] == 0 else None
    
    @staticmethod
    def update_session_context(session_id: str, context_data: Dict):
        """Update the working context for a session."""
        import uuid
        
        # Serialize context to JSON
        context_json = json.dumps(context_data)
        
        sql = f"""
        UPDATE agent_session 
        SET CONTEXT_SNAPSHOT = '{context_json}', END_TIME = SYSTIMESTAMP
        WHERE SESSION_ID = '{session_id}'
        """
        
        execute_dml(sql)
    
    @staticmethod
    def close_session(session_id: str):
        """Mark a session as inactive."""
        sql = f"""
        UPDATE agent_session 
        SET IS_ACTIVE = 'N', END_TIME = SYSTIMESTAMP
        WHERE SESSION_ID = '{session_id}'
        """
        
        execute_dml(sql)
    
    @staticmethod
    def get_active_sessions(agent_id: str = None) -> List[Dict]:
        """Get all active sessions, optionally filtered by agent."""
        
        if agent_id:
            sql = f"""SELECT s.SESSION_ID, s.AGENT_ID, a.AGENT_NAME as AGENT_NAME, 
                            s.START_TIME, s.IS_ACTIVE as SESSION_STATUS, 
                            s.WORKING_MEMORY_ID, m.VISIBILITY as WORKING_MEM_VISIBILITY
                     FROM agent_session s
                     LEFT JOIN agent_registry a ON s.AGENT_ID = a.AGENT_ID
                     LEFT JOIN memories m ON s.WORKING_MEMORY_ID = m.ID
                     WHERE s.IS_ACTIVE = 'Y' AND s.AGENT_ID = '{agent_id}'"""
        else:
            sql = """SELECT s.SESSION_ID, s.AGENT_ID, a.AGENT_NAME as AGENT_NAME, 
                           s.START_TIME, s.IS_ACTIVE as SESSION_STATUS, 
                           s.WORKING_MEMORY_ID, m.VISIBILITY as WORKING_MEM_VISIBILITY
                    FROM agent_session s
                    LEFT JOIN agent_registry a ON s.AGENT_ID = a.AGENT_ID
                    LEFT JOIN memories m ON s.WORKING_MEMORY_ID = m.ID
                    WHERE s.IS_ACTIVE = 'Y'"""
        
        return execute_query(sql)


# ============================================================================
# Access Audit API
# ============================================================================

class AccessAuditAPI:
    """API for memory access audit logging"""
    
    @staticmethod
    def log_access(agent_id: str, memory_id: int, access_type: str = "READ", 
                  session_token: str = None):
        """Log a memory access event."""
        
        sql = f"""
        INSERT INTO agent_memory_access (AGENT_ID, MEMORY_ID, ACCESS_TYPE, ACCESS_TIME)
        VALUES ('{agent_id}', {memory_id}, '{access_type}', SYSTIMESTAMP)
        """
        
        execute_dml(sql)
    
    @staticmethod
    def get_access_history(agent_id: str, limit: int = 50) -> List[Dict]:
        """Get access history for an agent."""
        
        sql = f"""SELECT AGENT_ID, MEMORY_ID, ACCESS_TYPE, ACCESS_TIME 
                  FROM agent_memory_access 
                  WHERE AGENT_ID = '{agent_id}'
                  ORDER BY ACCESS_TIME DESC
                  FETCH FIRST {limit} ROWS ONLY"""
        
        return execute_query(sql)


# ============================================================================
# Collaboration API
# ============================================================================

class CollaborationAPI:
    """API for agent-to-agent collaboration requests"""
    
    @staticmethod
    def request_collaboration(sharing_agent: str, receiving_agent: str, 
                            memory_id: int, reason: str = "") -> bool:
        """Request to share a collaborative memory with another agent."""
        
        sql = f"""
        INSERT INTO agent_collaboration (SHARING_AGENT, RECEIVING_AGENT, MEMORY_ID, 
                                        SHARE_REASON, STATUS, CREATED_AT)
        VALUES ('{sharing_agent}', '{receiving_agent}', {memory_id}, '{reason}', 
                'PENDING', SYSTIMESTAMP)
        """
        
        result = execute_dml(sql)
        return result['returncode'] == 0
    
    @staticmethod
    def approve_collaboration(collab_id: int):
        """Approve a collaboration request."""
        
        sql = f"""
        UPDATE agent_collaboration 
        SET STATUS = 'ACCEPTED', APPROVED_AT = SYSTIMESTAMP
        WHERE COLLAB_ID = {collab_id}
        """
        
        execute_dml(sql)
    
    @staticmethod
    def get_pending_requests(agent_id: str, role: str = "receiving") -> List[Dict]:
        """Get pending collaboration requests for an agent."""
        
        if role == "receiving":
            sql = f"""SELECT COLLAB_ID, SHARING_AGENT, RECEIVING_AGENT, MEMORY_ID, 
                            SHARE_REASON, STATUS, CREATED_AT
                     FROM agent_collaboration 
                     WHERE RECEIVING_AGENT = '{agent_id}' AND STATUS = 'PENDING'
                     ORDER BY CREATED_AT DESC"""
        else:  # "sharing"
            sql = f"""SELECT COLLAB_ID, SHARING_AGENT, RECEIVING_AGENT, MEMORY_ID, 
                            SHARE_REASON, STATUS, CREATED_AT
                     FROM agent_collaboration 
                     WHERE SHARING_AGENT = '{agent_id}' AND STATUS = 'PENDING'
                     ORDER BY CREATED_AT DESC"""
        
        return execute_query(sql)


# ============================================================================
# Utility Functions
# ============================================================================

def verify_schema_integrity() -> bool:
    """Verify that all required tables and views exist."""
    
    required_tables = [
        'AGENT_REGISTRY', 'MEMORIES', 
        'AGENT_MEMORY_ACCESS', 'AGENT_COLLABORATION', 'AGENT_SESSION'
    ]
    
    required_views = [
        'V_AGENT_ACCESSIBLE_MEMORIES', 'V_AGENT_CAPABILITIES', 'V_ACTIVE_SESSIONS'
    ]
    
    # Check tables
    table_check_sql = f"""SELECT TABLE_NAME FROM USER_TABLES 
                          WHERE TABLE_NAME IN ({','.join([f"'{t}'" for t in required_tables])})"""
    existing_tables = [r['TABLE_NAME'] for r in execute_query(table_check_sql)]
    
    # Check views
    view_check_sql = f"""SELECT VIEW_NAME FROM USER_VIEWS 
                         WHERE VIEW_NAME IN ({','.join([f"'{v}'" for v in required_views])})"""
    existing_views = [r['VIEW_NAME'] for r in execute_query(view_check_sql)]
    
    # Verify all components exist
    missing_tables = set(required_tables) - set(existing_tables)
    missing_views = set(required_views) - set(existing_views)
    
    if missing_tables or missing_views:
        print(f"⚠️ Missing tables: {missing_tables}")
        print(f"⚠️ Missing views: {missing_views}")
        return False
    
    return True


def get_memory_visibility_matrix() -> Dict[str, Any]:
    """Get statistics on memory visibility distribution."""
    
    sql = """SELECT VISIBILITY, COUNT(*) as MEMORY_COUNT
             FROM memories 
             GROUP BY VISIBILITY
             ORDER BY VISIBILITY"""
    
    results = execute_query(sql)
    
    matrix = {}
    for row in results:
        vis_type = row['VISIBILITY']
        count = int(row['MEMORY_COUNT']) if isinstance(row['MEMORY_COUNT'], str) else row['MEMORY_COUNT']
        matrix[vis_type] = {
            'count': count,
            'description': {
                'SHARED': 'Global shared knowledge',
                'PRIVATE': 'Agent-specific private memory',
                'COLLABORATIVE': 'Team-shared collaborative space'
            }.get(vis_type, '')
        }
    
    return matrix


# ============================================================================
# Main Execution - Example Usage
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("Oracle Memory System v0.4.2 - Multi-Agent Architecture API")
    print("=" * 70)
    
    # Verify schema integrity first
    print("\n[1] Verifying Schema Integrity...")
    if verify_schema_integrity():
        print("✅ All required tables and views exist")
    else:
        print("❌ Schema verification failed - please run agent_schema.sql first")
        exit(1)
    
    # Register sample agents
    print("\n[2] Registering Sample Agents...")
    
    AgentRegistryAPI.register_agent(
        agent_id="agent-analysis-01",
        agent_name="Analysis Agent",
        agent_type="analysis",
        capabilities=["data-analysis", "pattern-recognition"],
        description="AI agent for data analysis and pattern recognition"
    )
    
    AgentRegistryAPI.register_agent(
        agent_id="agent-writing-01", 
        agent_name="Writing Agent",
        agent_type="writing",
        capabilities=["content-generation", "documentation"],
        description="AI agent for content generation and documentation"
    )
    
    print("✅ Sample agents registered")
    
    # Create memories with different visibility levels
    print("\n[3] Creating Memories with Different Visibility...")
    
    # Shared memory - accessible to all agents
    shared_mem_id = MemoryVisibilityAPI.create_memory(
        memory_data={
            'content': 'Oracle Database Best Practices v1.0',
            'category': 'documentation',
            'priority': 1
        },
        visibility="SHARED"
    )
    
    # Private memory - only for analysis agent
    private_mem_id = MemoryVisibilityAPI.create_memory(
        memory_data={
            'content': 'Analysis Agent Personal Configuration and Preferences',
            'category': 'configuration', 
            'priority': 2
        },
        agent_id="agent-analysis-01",
        visibility="PRIVATE"
    )
    
    # Collaborative memory - shared between analysis and writing agents
    collab_mem_id = MemoryVisibilityAPI.create_memory(
        memory_data={
            'content': 'Joint Research Project Notes',
            'category': 'collaboration',
            'priority': 1
        },
        visibility="COLLABORATIVE",
        accessible_to=["agent-analysis-01", "agent-writing-01"]
    )
    
    print(f"✅ Created: SHARED(mem={shared_mem_id}), PRIVATE(mem={private_mem_id}), COLLABORATIVE(mem={collab_mem_id})")
    
    # Test memory access for each agent
    print("\n[4] Testing Memory Access Per Agent...")
    
    # Analysis Agent can see all three types
    analysis_access = MemoryVisibilityAPI.get_agent_memories("agent-analysis-01")
    print(f"   📊 Analysis Agent memories: {len(analysis_access)} items")
    
    # Writing Agent can only see SHARED and COLLABORATIVE (not PRIVATE)  
    writing_access = MemoryVisibilityAPI.get_agent_memories("agent-writing-01")
    print(f"   📊 Writing Agent memories: {len(writing_access)} items")
    
    # Get visibility matrix statistics
    print("\n[5] Memory Visibility Distribution:")
    visibility_matrix = get_memory_visibility_matrix()
    for vis_type, stats in visibility_matrix.items():
        print(f"   • {vis_type}: {stats['count']} memories ({stats['description']})")
    
    # Create agent session
    print("\n[6] Creating Agent Session...")
    session_id = AgentSessionAPI.create_session("agent-analysis-01", working_memory_id=shared_mem_id)
    print(f"   ✅ Session created: {session_id}")
    
    # Update session context
    AgentSessionAPI.update_session_context(session_id, {
        'current_task': 'data_analysis',
        'progress': 0.25,
        'focus_area': 'pattern_detection'
    })
    
    # Get active sessions
    active_sessions = AgentSessionAPI.get_active_sessions("agent-analysis-01")
    print(f"   📋 Active sessions for agent: {len(active_sessions)}")
    
    # Log access events
    print("\n[7] Logging Access Events...")
    AccessAuditAPI.log_access("agent-analysis-01", shared_mem_id, "READ")
    AccessAuditAPI.log_access("agent-analysis-01", private_mem_id, "WRITE")
    
    # Get access history
    access_history = AccessAuditAPI.get_access_history("agent-analysis-01", limit=10)
    print(f"   📜 Recent accesses: {len(access_history)} events")
    
    print("\n" + "=" * 70)
    print("✅ Multi-Agent Architecture API Test Complete!")
    print("=" * 70)
