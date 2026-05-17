"""
Oracle Memory System v0.4.2 - Multi-Agent Architecture Integration Test
=========================================================================
Description: Comprehensive integration test for multi-agent memory architecture
Version: 1.0
Author: Haiwen Yin (胖头鱼 🐟)
Date: 2026-05-07

This script performs end-to-end testing of the multi-agent architecture including:
- Schema validation after DDL execution
- Agent registration and discovery
- Memory creation with visibility control
- Access pattern verification across agent types
- Session management functionality
- Collaboration workflow validation
"""

import sys
import os
from datetime import datetime
from typing import List, Dict, Any

# Add the scripts directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from agent_api import (
    execute_query, 
    execute_dml,
    AgentRegistryAPI,
    MemoryVisibilityAPI,
    AgentSessionAPI,
    AccessAuditAPI,
    CollaborationAPI,
    verify_schema_integrity,
    get_memory_visibility_matrix
)


# ============================================================================
# Test Framework
# ============================================================================

class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.error = None
    
    def record_success(self):
        self.passed = True
    
    def record_failure(self, error: Exception):
        self.passed = False
        self.error = str(error)
    
    def __repr__(self):
        status = "✅ PASS" if self.passed else f"❌ FAIL ({self.error})"
        return f"{self.name}: {status}"


class TestSuite:
    def __init__(self, name: str):
        self.name = name
        self.results: List[TestResult] = []
    
    def add_result(self, result: TestResult):
        self.results.append(result)
    
    def summary(self) -> Dict[str, int]:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        return {'total': total, 'passed': passed, 'failed': failed}


# ============================================================================
# Test Functions
# ============================================================================

def test_schema_validation(suite: TestSuite):
    """Test 1: Validate schema components exist after DDL execution."""
    
    result = TestResult("Schema Validation")
    
    try:
        # Verify all required tables
        table_check_sql = """SELECT COUNT(*) FROM USER_TABLES 
                             WHERE TABLE_NAME IN (
                                 'AGENT_REGISTRY', 'AGENT_MEMORY_ACCESS', 
                                 'AGENT_COLLABORATION', 'AGENT_SESSION'
                             )"""
        count_result = execute_query(table_check_sql)
        table_count = int(count_result[0]['COUNT(*)']) if count_result else 0
        
        if table_count < 4:
            result.record_failure(f"Only {table_count}/4 required tables found")
            return
        
        # Verify all required views
        view_check_sql = """SELECT COUNT(*) FROM USER_VIEWS 
                           WHERE VIEW_NAME IN (
                               'V_AGENT_ACCESSIBLE_MEMORIES', 
                               'V_AGENT_CAPABILITIES', 
                               'V_ACTIVE_SESSIONS'
                           )"""
        view_result = execute_query(view_check_sql)
        view_count = int(view_result[0]['COUNT(*)']) if view_result else 0
        
        if view_count < 3:
            result.record_failure(f"Only {view_count}/3 required views found")
            return
        
        # Verify MEMORIES table has new columns
        column_check_sql = """SELECT COUNT(*) FROM USER_TAB_COLUMNS 
                              WHERE TABLE_NAME = 'MEMORIES' AND COLUMN_NAME IN (
                                  'OWNED_BY_AGENT', 'VISIBILITY', 'ACCESSIBLE_TO'
                              )"""
        col_result = execute_query(column_check_sql)
        col_count = int(col_result[0]['COUNT(*)']) if col_result else 0
        
        if col_count < 3:
            result.record_failure(f"Only {col_count}/3 new columns in MEMORIES found")
            return
        
        result.record_success()
        
    except Exception as e:
        result.record_failure(str(e))
    
    suite.add_result(result)


def test_agent_registration(suite: TestSuite):
    """Test 2: Agent registration and discovery functionality."""
    
    # Register test agents
    AgentRegistryAPI.register_agent(
        agent_id="test-agent-analysis",
        agent_name="Test Analysis Agent", 
        agent_type="analysis",
        capabilities=["data-analysis", "pattern-recognition"],
        description="Testing agent for analysis"
    )
    
    AgentRegistryAPI.register_agent(
        agent_id="test-agent-writing",
        agent_name="Test Writing Agent",
        agent_type="writing", 
        capabilities=["content-generation", "documentation"],
        description="Testing agent for writing"
    )
    
    AgentRegistryAPI.register_agent(
        agent_id="test-agent-deployment",
        agent_name="Test Deployment Agent",
        agent_type="deployment",
        capabilities=["deployment", "configuration-management"],
        description="Testing agent for deployment"
    )
    
    # Test 2a: Get registered agent
    result_1 = TestResult("Agent Registration - Retrieve by ID")
    try:
        agent = AgentRegistryAPI.get_agent("test-agent-analysis")
        if not agent or agent.get('AGENT_NAME') != "Test Analysis Agent":
            result_1.record_failure(f"Invalid agent retrieved: {agent}")
        else:
            result_1.record_success()
    except Exception as e:
        result_1.record_failure(str(e))
    
    suite.add_result(result_1)
    
    # Test 2b: Find agents by type
    result_2 = TestResult("Agent Registration - Query by Type")
    try:
        analysis_agents = AgentRegistryAPI.find_agents_by_type("analysis")
        if len(analysis_agents) < 1:
            result_2.record_failure(f"No analysis agents found")
        else:
            result_2.record_success()
    except Exception as e:
        result_2.record_failure(str(e))
    
    suite.add_result(result_2)
    
    # Test 2c: Find agents by capability
    result_3 = TestResult("Agent Registration - Query by Capability")
    try:
        writing_agents = AgentRegistryAPI.find_agents_by_capability("content-generation")
        if len(writing_agents) < 1:
            result_3.record_failure(f"No writing agents found")
        else:
            result_3.record_success()
    except Exception as e:
        result_3.record_failure(str(e))
    
    suite.add_result(result_3)


def test_memory_visibility(suite: TestSuite):
    """Test 3: Memory visibility and access control."""
    
    # Create memories with different visibility levels
    shared_mem_id = MemoryVisibilityAPI.create_memory(
        memory_data={
            'content': 'Shared System Documentation',
            'category': 'documentation',
            'priority': 1
        },
        visibility="SHARED"
    )
    
    private_mem_id = MemoryVisibilityAPI.create_memory(
        memory_data={
            'content': 'Analysis Agent Private Configuration',
            'category': 'configuration',
            'priority': 2
        },
        agent_id="test-agent-analysis",
        visibility="PRIVATE"
    )
    
    collab_mem_id = MemoryVisibilityAPI.create_memory(
        memory_data={
            'content': 'Joint Project Notes',
            'category': 'collaboration',
            'priority': 1
        },
        visibility="COLLABORATIVE",
        accessible_to=["test-agent-analysis", "test-agent-writing"]
    )
    
    # Test 3a: SHARED memory access (both agents should see it)
    result_1 = TestResult("Memory Visibility - SHARED Access")
    try:
        analysis_access = MemoryVisibilityAPI.get_agent_memories("test-agent-analysis")
        writing_access = MemoryVisibilityAPI.get_agent_memories("test-agent-writing")
        
        shared_found_analysis = any(m['memory_id'] == str(shared_mem_id) or m['memory_id'] == shared_mem_id 
                                   for m in analysis_access)
        shared_found_writing = any(m['memory_id'] == str(shared_mem_id) or m['memory_id'] == shared_mem_id 
                                  for m in writing_access)
        
        if not (shared_found_analysis and shared_found_writing):
            result_1.record_failure(f"SHARED memory not visible to both agents")
        else:
            result_1.record_success()
    except Exception as e:
        result_1.record_failure(str(e))
    
    suite.add_result(result_1)
    
    # Test 3b: PRIVATE memory access (only owner should see it)
    result_2 = TestResult("Memory Visibility - PRIVATE Access")
    try:
        analysis_access = MemoryVisibilityAPI.get_agent_memories("test-agent-analysis")
        writing_access = MemoryVisibilityAPI.get_agent_memories("test-agent-writing")
        
        private_found_analysis = any(m['memory_id'] == str(private_mem_id) or m['memory_id'] == private_mem_id 
                                    for m in analysis_access)
        private_found_writing = any(m['memory_id'] == str(private_mem_id) or m['memory_id'] == private_mem_id 
                                   for m in writing_access)
        
        if not (private_found_analysis and not private_found_writing):
            result_2.record_failure(f"PRIVATE memory access control failed")
        else:
            result_2.record_success()
    except Exception as e:
        result_2.record_failure(str(e))
    
    suite.add_result(result_2)
    
    # Test 3c: COLLABORATIVE memory access (both listed agents should see it)
    result_3 = TestResult("Memory Visibility - COLLABORATIVE Access")
    try:
        analysis_access = MemoryVisibilityAPI.get_agent_memories("test-agent-analysis")
        writing_access = MemoryVisibilityAPI.get_agent_memories("test-agent-writing")
        
        collab_found_analysis = any(m['memory_id'] == str(collab_mem_id) or m['memory_id'] == collab_mem_id 
                                   for m in analysis_access)
        collab_found_writing = any(m['memory_id'] == str(collab_mem_id) or m['memory_id'] == collab_mem_id 
                                  for m in writing_access)
        
        if not (collab_found_analysis and collab_found_writing):
            result_3.record_failure(f"COLLABORATIVE memory access control failed")
        else:
            result_3.record_success()
    except Exception as e:
        result_3.record_failure(str(e))
    
    suite.add_result(result_3)


def test_session_management(suite: TestSuite):
    """Test 4: Agent session management."""
    
    # Create active sessions for each agent
    analysis_session = AgentSessionAPI.create_session("test-agent-analysis", working_memory_id=shared_mem_id)
    writing_session = AgentSessionAPI.create_session("test-agent-writing", working_memory_id=collab_mem_id)
    
    result_1 = TestResult("Session Management - Create Session")
    try:
        if not analysis_session or not writing_session:
            result_1.record_failure(f"Failed to create sessions")
        else:
            result_1.record_success()
    except Exception as e:
        result_1.record_failure(str(e))
    
    suite.add_result(result_1)
    
    # Update session context
    AgentSessionAPI.update_session_context(analysis_session, {
        'current_task': 'data_analysis',
        'progress': 0.5,
        'focus_area': 'pattern_detection'
    })
    
    result_2 = TestResult("Session Management - Update Context")
    try:
        # Verify by checking session exists and is active
        sessions = AgentSessionAPI.get_active_sessions("test-agent-analysis")
        if len(sessions) < 1:
            result_2.record_failure(f"No active session found after update")
        else:
            result_2.record_success()
    except Exception as e:
        result_2.record_failure(str(e))
    
    suite.add_result(result_2)


def test_access_audit(suite: TestSuite):
    """Test 5: Access audit logging."""
    
    # Log some access events
    AccessAuditAPI.log_access("test-agent-analysis", shared_mem_id, "READ")
    AccessAuditAPI.log_access("test-agent-analysis", private_mem_id, "WRITE")
    AccessAuditAPI.log_access("test-agent-writing", collab_mem_id, "READ")
    
    result = TestResult("Access Audit - Log and Retrieve History")
    try:
        history = AccessAuditAPI.get_access_history("test-agent-analysis")
        if len(history) < 2:
            result.record_failure(f"Expected at least 2 access records, got {len(history)}")
        else:
            result.record_success()
    except Exception as e:
        result.record_failure(str(e))
    
    suite.add_result(result)


def test_collaboration(suite: TestSuite):
    """Test 6: Collaboration request workflow."""
    
    # Request collaboration
    collab_request = CollaborationAPI.request_collaboration(
        sharing_agent="test-agent-analysis",
        receiving_agent="test-agent-writing",
        memory_id=shared_mem_id,
        reason="Share analysis methodology"
    )
    
    result_1 = TestResult("Collaboration - Create Request")
    try:
        if not collab_request:
            result_1.record_failure(f"Failed to create collaboration request")
        else:
            result_1.record_success()
    except Exception as e:
        result_1.record_failure(str(e))
    
    suite.add_result(result_1)
    
    # Get pending requests
    result_2 = TestResult("Collaboration - Retrieve Pending Requests")
    try:
        pending = CollaborationAPI.get_pending_requests("test-agent-writing", role="receiving")
        if len(pending) < 1:
            result_2.record_failure(f"No pending requests found")
        else:
            result_2.record_success()
    except Exception as e:
        result_2.record_failure(str(e))
    
    suite.add_result(result_2)


# ============================================================================
# Main Test Execution
# ============================================================================

def main():
    print("=" * 80)
    print("Oracle Memory System v0.4.2 - Multi-Agent Architecture Integration Tests")
    print("=" * 80)
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 80)
    
    # Check schema integrity first
    print("\n[PRE-FLIGHT CHECK] Verifying schema integrity...")
    if not verify_schema_integrity():
        print("❌ Schema verification failed. Please run agent_schema.sql before testing.")
        return False
    
    print("✅ Schema integrity verified\n")
    
    # Run all test suites
    all_passed = True
    
    # Test Suite 1: Schema Validation
    suite_1 = TestSuite("Schema Validation Tests")
    test_schema_validation(suite_1)
    
    # Test Suite 2: Agent Registration
    suite_2 = TestSuite("Agent Registration Tests")
    test_agent_registration(suite_2)
    
    # Test Suite 3: Memory Visibility
    suite_3 = TestSuite("Memory Visibility Tests")
    test_memory_visibility(suite_3)
    
    # Test Suite 4: Session Management
    suite_4 = TestSuite("Session Management Tests")
    test_session_management(suite_4)
    
    # Test Suite 5: Access Audit
    suite_5 = TestSuite("Access Audit Tests")
    test_access_audit(suite_5)
    
    # Test Suite 6: Collaboration
    suite_6 = TestSuite("Collaboration Workflow Tests")
    test_collaboration(suite_6)
    
    # Print Results Summary
    print("\n" + "=" * 80)
    print("TEST RESULTS SUMMARY")
    print("=" * 80)
    
    total_tests = 0
    total_passed = 0
    
    for i, suite in enumerate([suite_1, suite_2, suite_3, suite_4, suite_5, suite_6], 1):
        summary = suite.summary()
        print(f"\n[{i}] {suite.name}")
        print("-" * 60)
        
        for result in suite.results:
            print(f"   {result}")
        
        total_tests += summary['total']
        total_passed += summary['passed']
        
        if summary['failed'] > 0:
            all_passed = False
    
    # Overall Summary
    print("\n" + "=" * 80)
    print("OVERALL TEST SUMMARY")
    print("=" * 80)
    print(f"Total Tests: {total_tests}")
    print(f"Passed: {total_passed} ✅")
    print(f"Failed: {total_tests - total_passed} ❌")
    
    if all_passed:
        print("\n🎉 ALL TESTS PASSED!")
    else:
        print("\n⚠️ Some tests failed. Please review the details above.")
    
    # Print memory visibility statistics
    print("\n" + "=" * 80)
    print("MEMORY VISIBILITY DISTRIBUTION")
    print("=" * 80)
    visibility_matrix = get_memory_visibility_matrix()
    for vis_type, stats in visibility_matrix.items():
        print(f"{vis_type}: {stats['count']} memories - {stats['description']}")
    
    # Print active sessions
    print("\n" + "=" * 80)
    print("ACTIVE SESSIONS")
    print("=" * 80)
    sessions = AgentSessionAPI.get_active_sessions()
    for session in sessions:
        status = "ACTIVE" if session.get('SESSION_STATUS') == 'Y' else "INACTIVE"
        print(f"{session['SESSION_ID']} - {session.get('AGENT_NAME', '')} [{status}]")
    
    # End time
    end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\nEnd Time: {end_time}")
    print("=" * 80)
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
