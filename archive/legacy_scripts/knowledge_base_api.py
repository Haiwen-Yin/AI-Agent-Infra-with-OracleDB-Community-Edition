#!/usr/bin/env python3
"""
Oracle Memory System v1.0.0 - Knowledge Base Python API
============================================================================
Description: Python API for Knowledge Base operations with Knowledge Graph support
Version: 1.0.0-KB-PYTHON
Author: Haiwen Yin (胖头鱼 🐟)
Date: 2026-05-09
Requirements:
- Python 3.8+
- Oracle SQLcl at /root/sqlcl/bin/sql
- BGE-M3 embedding API at http://10.10.10.1:12345/v1
============================================================================
"""

import json
import subprocess
import urllib.request
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

# Configuration
SQLCL_PATH = "/root/sqlcl/bin/sql"
DB_CONNECTION = "openclaw/hermes@//10.10.10.130:1521/openclaw"
BGE_M3_API = "http://10.10.10.1:12345/v1/embeddings"
BGE_M3_MODEL = "text-embedding-bge-m3"

class KnowledgeBaseAPI:
    """Python API for Knowledge Base operations"""
    
    def __init__(self, db_connection: str = None):
        """
        Initialize Knowledge Base API
        
        Args:
            db_connection: Oracle database connection string
        """
        self.db_connection = db_connection or DB_CONNECTION
        self.sqlcl_path = SQLCL_PATH
    
    def execute_sql(self, sql: str) -> Tuple[bool, str]:
        """
        Execute SQL via SQLcl
        
        Args:
            sql: SQL statement to execute
            
        Returns:
            Tuple of (success, output)
        """
        cmd = f'echo "{sql}" | {self.sqlcl_path} {self.db_connection}'
        
        try:
            process = subprocess.run(
                ['bash', '-c', cmd],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            output = process.stdout + process.stderr
            
            # Check for actual ORA errors (not just warnings)
            # ORA-00942: table or view does not exist
            # ORA-06550: PL/SQL compilation error
            # ORA-22849: Type VECTOR not supported
            actual_errors = ['ORA-00942', 'ORA-06550', 'ORA-22849', 'ORA-01003']
            has_critical_error = any(error in output for error in actual_errors)
            
            # Success if returncode is 0 and no critical errors
            success = process.returncode == 0 and not has_critical_error
            
            return success, output
            
        except subprocess.TimeoutExpired:
            return False, "Timeout expired"
        except Exception as e:
            return False, str(e)
    
    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding using BGE-M3 model
        
        Args:
            text: Text to embed
            
        Returns:
            List of float values (1024 dimensions)
        """
        payload = json.dumps({
            "model": BGE_M3_MODEL,
            "input": text
        }).encode('utf-8')
        
        req = urllib.request.Request(
            BGE_M3_API,
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.loads(response.read().decode('utf-8'))
                
                if "data" in result and len(result["data"]) > 0:
                    return result["data"][0]["embedding"]
                else:
                    raise Exception("Unexpected API response format")
                    
        except Exception as e:
            raise Exception(f"Error generating embedding: {e}")
    
    # ============================================
    # KNOWLEDGE CONCEPT OPERATIONS
    # ============================================
    
    def create_concept(
        self,
        concept_name: str,
        concept_type: str,
        category: str,
        title: str,
        description: str,
        content: str,
        source_type: str = "MANUAL",
        source_memory_ids: List[int] = None,
        tags: List[str] = None,
        confidence: float = 0.8
    ) -> int:
        """
        Create new knowledge concept
        
        Args:
            concept_name: Human-readable name
            concept_type: FACT/RULE/PATTERN/EXPERIENCE/PRINCIPLE
            category: Domain category
            title: Short title
            description: Detailed description
            content: Full knowledge content
            source_type: MANUAL/DISTILLED/IMPORTED/VERIFIED
            source_memory_ids: Source memory IDs (for distillation)
            tags: List of tags
            confidence: Confidence score (0.0 - 1.0)
            
        Returns:
            Created concept ID
        """
        # Generate embedding for content
        embedding = self.generate_embedding(content)
        embedding_str = json.dumps(embedding)
        
        # Prepare JSON arrays
        source_memory_json = json.dumps(source_memory_ids or [])
        tags_json = json.dumps(tags or [])
        
        # Escape single quotes in strings
        content_escaped = content.replace("'", "''")
        description_escaped = description.replace("'", "''")
        title_escaped = title.replace("'", "''")
        
        sql = f"""
DECLARE
    v_concept_id NUMBER;
    l_vec CLOB;
BEGIN
    v_concept_id := knowledge_base_api.create_concept(
        p_concept_name => '{concept_name}',
        p_concept_type => '{concept_type}',
        p_category => '{category}',
        p_title => '{title_escaped}',
        p_description => '{description_escaped}',
        p_content => '{content_escaped}',
        p_source_type => '{source_type}',
        p_source_memory_ids => '{source_memory_json}',
        p_tags => '{tags_json}',
        p_confidence => {confidence}
    );
    
    -- Update embedding using TO_VECTOR
    l_vec := '{embedding_str}';
    UPDATE KNOWLEDGE_CONCEPTS
    SET EMBEDDING = TO_VECTOR(l_vec)
    WHERE CONCEPT_ID = v_concept_id;
    
    DBMS_OUTPUT.PUT_LINE(v_concept_id);
    COMMIT;
END;
"""
        
        success, output = self.execute_sql(sql)
        
        if success:
            # Query database for the last created concept
            query_sql = "SELECT KNOWLEDGE_CONCEPTS_SEQ.CURRVAL FROM DUAL"
            query_success, query_output = self.execute_sql(query_sql)
            
            if query_success:
                for line in query_output.split('\n'):
                    line = line.strip()
                    if line.isdigit():
                        return int(line)
            
            # Fallback: query by name and timestamp
            fallback_sql = f"""
SELECT CONCEPT_ID FROM KNOWLEDGE_CONCEPTS 
WHERE CONCEPT_NAME = '{concept_name}' 
ORDER BY CREATED_AT DESC FETCH FIRST 1 ROWS ONLY
"""
            fallback_success, fallback_output = self.execute_sql(fallback_sql)
            
            if fallback_success:
                for line in fallback_output.split('\n'):
                    line = line.strip()
                    if line.isdigit():
                        return int(line)
        
        raise Exception(f"Failed to create concept: {output[:500]}")
    
    def get_concept(self, concept_id: int) -> Dict[str, Any]:
        """
        Get knowledge concept by ID
        
        Args:
            concept_id: Concept ID
            
        Returns:
            Concept data dictionary
        """
        # Use simple SELECT with only essential fields
        sql = f"SELECT CONCEPT_ID, CONCEPT_NAME, CONCEPT_TYPE, CATEGORY, TITLE, VALIDATION_STATUS, CONFIDENCE, VERSION, SOURCE_TYPE FROM KNOWLEDGE_CONCEPTS WHERE CONCEPT_ID = {concept_id}"
        
        success, output = self.execute_sql(sql)
        
        if success:
            # Parse SQLcl table output
            lines = output.split('\n')
            for i, line in enumerate(lines):
                # Look for separator line with underscores
                if '___' in line and 'CONCEPT_ID' in lines[i-1]:
                    # Found header and separator, next line is data
                    if i + 1 < len(lines):
                        data_line = lines[i + 1].strip()
                        # Split by whitespace, handle multiple spaces
                        parts = data_line.split()
                        if len(parts) >= 9:
                            try:
                                return {
                                    'concept_id': int(parts[0]),
                                    'concept_name': parts[1],
                                    'concept_type': parts[2],
                                    'category': parts[3] if parts[3] != 'null' else None,
                                    'title': ' '.join(parts[4:-4]) if len(parts) > 8 else parts[4],
                                    'validation_status': parts[-4],
                                    'confidence': float(parts[-3]),
                                    'version': int(parts[-2]),
                                    'source_type': parts[-1]
                                }
                            except (ValueError, IndexError) as e:
                                # Return basic info if parsing fails
                                return {
                                    'concept_id': int(parts[0]),
                                    'concept_name': parts[1],
                                    'concept_type': parts[2],
                                    'error': f'Partial parse: {str(e)}'
                                }
        
        return {"error": "Concept not found"}
    
    def update_concept(
        self,
        concept_id: int,
        title: str = None,
        description: str = None,
        content: str = None,
        change_summary: str = None,
        change_reason: str = None
    ) -> bool:
        """
        Update knowledge concept
        
        Args:
            concept_id: Concept ID to update
            title: New title (optional)
            description: New description (optional)
            content: New content (optional)
            change_summary: Summary of changes
            change_reason: Reason for change
            
        Returns:
            True if successful
        """
        # Build dynamic update statement
        updates = []
        if title:
            updates.append(f"p_title => '{title}'")
        if description:
            updates.append(f"p_description => '{description.replace(chr(39), chr(39)+chr(39))}'")
        if content:
            updates.append(f"p_content => '{content.replace(chr(39), chr(39)+chr(39))}'")
        if change_summary:
            updates.append(f"p_change_summary => '{change_summary.replace(chr(39), chr(39)+chr(39))}'")
        if change_reason:
            updates.append(f"p_change_reason => '{change_reason}'")
        
        if not updates:
            return True
        
        sql = f"""
BEGIN
    knowledge_base_api.update_concept(
        p_concept_id => {concept_id},
        {', '.join(updates)}
    );
    COMMIT;
END;
"""
        
        success, output = self.execute_sql(sql)
        return success
    
    def validate_concept(
        self,
        concept_id: int,
        validation_status: str,
        confidence: float = 1.0
    ) -> bool:
        """
        Validate knowledge concept
        
        Args:
            concept_id: Concept ID
            validation_status: VALIDATED/REJECTED
            confidence: Confidence score
            
        Returns:
            True if successful
        """
        sql = f"""
BEGIN
    knowledge_base_api.validate_concept(
        p_concept_id => {concept_id},
        p_validation_status => '{validation_status}',
        p_confidence => {confidence}
    );
    COMMIT;
END;
"""
        
        success, output = self.execute_sql(sql)
        return success
    
    def deprecate_concept(self, concept_id: int, reason: str) -> bool:
        """
        Deprecate knowledge concept
        
        Args:
            concept_id: Concept ID
            reason: Reason for deprecation
            
        Returns:
            True if successful
        """
        sql = f"""
BEGIN
    knowledge_base_api.deprecate_concept(
        p_concept_id => {concept_id},
        p_reason => '{reason}'
    );
    COMMIT;
END;
"""
        
        success, output = self.execute_sql(sql)
        return success
    
    # ============================================
    # KNOWLEDGE GRAPH OPERATIONS
    # ============================================
    
    def create_relationship(
        self,
        source_concept_id: int,
        target_concept_id: int,
        relationship_type: str,
        strength: float = 1.0,
        properties: Dict = None
    ) -> int:
        """
        Create relationship between concepts
        
        Args:
            source_concept_id: Source concept ID
            target_concept_id: Target concept ID
            relationship_type: IS_A/PART_OF/CAUSES/ENABLES/CONTRADICTS/SUPPORTS
            strength: Relationship strength (0.0 - 1.0)
            properties: Additional properties (JSON)
            
        Returns:
            Created relationship ID
        """
        properties_json = json.dumps(properties or {})
        
        sql = f"""
DECLARE
    v_rel_id NUMBER;
BEGIN
    v_rel_id := knowledge_base_api.create_relationship(
        p_source_concept_id => {source_concept_id},
        p_target_concept_id => {target_concept_id},
        p_relationship_type => '{relationship_type}',
        p_strength => {strength},
        p_properties => '{properties_json}'
    );
    DBMS_OUTPUT.PUT_LINE(v_rel_id);
    COMMIT;
END;
"""
        
        success, output = self.execute_sql(sql)
        
        if success:
            # Query database for the last created relationship
            query_sql = "SELECT KNOWLEDGE_GRAPH_SEQ.CURRVAL FROM DUAL"
            query_success, query_output = self.execute_sql(query_sql)
            
            if query_success:
                for line in query_output.split('\n'):
                    line = line.strip()
                    if line.isdigit():
                        return int(line)
            
            # Fallback: query by source and target
            fallback_sql = f"""
SELECT RELATIONSHIP_ID FROM KNOWLEDGE_GRAPH 
WHERE SOURCE_CONCEPT_ID = {source_concept_id} AND TARGET_CONCEPT_ID = {target_concept_id}
ORDER BY CREATED_AT DESC FETCH FIRST 1 ROWS ONLY
"""
            fallback_success, fallback_output = self.execute_sql(fallback_sql)
            
            if fallback_success:
                for line in fallback_output.split('\n'):
                    line = line.strip()
                    if line.isdigit():
                        return int(line)
        
        raise Exception(f"Failed to create relationship: {output[:500]}")
    
    def get_relationships(
        self,
        concept_id: int,
        direction: str = "BOTH"
    ) -> List[Dict[str, Any]]:
        """
        Get concept relationships
        
        Args:
            concept_id: Concept ID
            direction: OUTGOING/INCOMING/BOTH
            
        Returns:
            List of relationship dictionaries
        """
        # Build WHERE clause based on direction
        if direction == "OUTGOING":
            where_clause = f"kg.SOURCE_CONCEPT_ID = {concept_id}"
        elif direction == "INCOMING":
            where_clause = f"kg.TARGET_CONCEPT_ID = {concept_id}"
        else:  # BOTH
            where_clause = f"(kg.SOURCE_CONCEPT_ID = {concept_id} OR kg.TARGET_CONCEPT_ID = {concept_id})"
        
        sql = f"""
SELECT kg.RELATIONSHIP_ID, kc_s.CONCEPT_NAME as SOURCE_NAME, kg.RELATIONSHIP_TYPE, kc_t.CONCEPT_NAME as TARGET_NAME, kg.RELATIONSHIP_STRENGTH
FROM KNOWLEDGE_GRAPH kg
JOIN KNOWLEDGE_CONCEPTS kc_s ON kg.SOURCE_CONCEPT_ID = kc_s.CONCEPT_ID
JOIN KNOWLEDGE_CONCEPTS kc_t ON kg.TARGET_CONCEPT_ID = kc_t.CONCEPT_ID
WHERE {where_clause}
"""
        
        success, output = self.execute_sql(sql)
        
        relationships = []
        if success:
            lines = output.split('\n')
            for i, line in enumerate(lines):
                if '___' in line and 'RELATIONSHIP_ID' in lines[i-1]:
                    # Found separator, parse data lines
                    j = i + 1
                    while j < len(lines) and lines[j].strip() and '___' not in lines[j]:
                        data_line = lines[j].strip()
                        parts = data_line.split()
                        if len(parts) >= 5:
                            try:
                                relationships.append({
                                    'relationship_id': int(parts[0]),
                                    'source_name': parts[1],
                                    'relationship_type': parts[2],
                                    'target_name': parts[3],
                                    'strength': float(parts[4])
                                })
                            except (ValueError, IndexError):
                                pass
                        j += 1
                    break
        
        return relationships
    
    def traverse_graph(
        self,
        start_concept_id: int,
        max_hops: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Traverse knowledge graph
        
        Args:
            start_concept_id: Starting concept ID
            max_hops: Maximum hops to traverse
            
        Returns:
            List of traversal results
        """
        sql = f"SELECT knowledge_base_api.traverse_graph({start_concept_id}, {max_hops}) FROM DUAL"
        
        success, output = self.execute_sql(sql)
        
        if success:
            for line in output.split('\n'):
                if line.strip().startswith('['):
                    return json.loads(line.strip())
        
        return []
    
    # ============================================
    # SEMANTIC SEARCH OPERATIONS
    # ============================================
    
    def semantic_search(
        self,
        query_text: str,
        limit: int = 10,
        min_confidence: float = 0.5,
        category: str = None,
        concept_type: str = None
    ) -> List[Dict[str, Any]]:
        """
        Semantic search for knowledge
        
        Args:
            query_text: Search query
            limit: Maximum results
            min_confidence: Minimum confidence threshold
            category: Filter by category
            concept_type: Filter by concept type
            
        Returns:
            List of matching concepts
        """
        # Escape single quotes
        query_escaped = query_text.replace("'", "''")
        
        # Build optional parameters
        optional_params = ""
        if category:
            optional_params += f", p_category => '{category}'"
        if concept_type:
            optional_params += f", p_concept_type => '{concept_type}'"
        
        sql = f"SELECT knowledge_base_api.semantic_search('{query_escaped}', {limit}, {min_confidence}{optional_params}) FROM DUAL"
        
        success, output = self.execute_sql(sql)
        
        if success:
            for line in output.split('\n'):
                if line.strip().startswith('['):
                    return json.loads(line.strip())
        
        return []
    
    # ============================================
    # KNOWLEDGE DISTILLATION OPERATIONS
    # ============================================
    
    def distill_experience(
        self,
        memory_ids: List[int],
        knowledge_type: str = "EXPERIENCE",
        min_pattern_count: int = 3
    ) -> int:
        """
        Distill experience from memories
        
        Args:
            memory_ids: List of memory IDs
            knowledge_type: Type of knowledge to create
            min_pattern_count: Minimum memories required
            
        Returns:
            Created knowledge ID
        """
        memory_ids_json = json.dumps(memory_ids)
        
        sql = f"""
DECLARE
    v_knowledge_id NUMBER;
BEGIN
    v_knowledge_id := knowledge_base_api.distill_experience(
        p_memory_ids => '{memory_ids_json}',
        p_knowledge_type => '{knowledge_type}',
        p_min_pattern_count => {min_pattern_count}
    );
    DBMS_OUTPUT.PUT_LINE(v_knowledge_id);
    COMMIT;
END;
"""
        
        success, output = self.execute_sql(sql)
        
        if success:
            for line in output.split('\n'):
                if line.strip().isdigit():
                    return int(line.strip())
        
        raise Exception(f"Failed to distill experience: {output}")
    
    def get_distillation_candidates(
        self,
        category: str = None,
        min_age_days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Get distillation candidates
        
        Args:
            category: Filter by category
            min_age_days: Minimum age in days
            
        Returns:
            List of distillation candidates
        """
        category_param = f"'{category}'" if category else "NULL"
        
        sql = f"SELECT knowledge_base_api.get_distillation_candidates({category_param}, {min_age_days}) FROM DUAL"
        
        success, output = self.execute_sql(sql)
        
        if success:
            for line in output.split('\n'):
                if line.strip().startswith('['):
                    return json.loads(line.strip())
        
        return []
    
    # ============================================
    # STATISTICS AND MONITORING
    # ============================================
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get knowledge base statistics
        
        Returns:
            Statistics dictionary
        """
        # Use direct SQL queries instead of PL/SQL function
        sql = """
SELECT 
    (SELECT COUNT(*) FROM KNOWLEDGE_CONCEPTS) as total_concepts,
    (SELECT COUNT(*) FROM KNOWLEDGE_CONCEPTS WHERE VALIDATION_STATUS = 'VALIDATED') as validated_concepts,
    (SELECT COUNT(*) FROM KNOWLEDGE_CONCEPTS WHERE VALIDATION_STATUS = 'PENDING') as pending_concepts,
    (SELECT COUNT(*) FROM KNOWLEDGE_GRAPH) as total_relationships,
    (SELECT COUNT(*) FROM KNOWLEDGE_DISTILLATION_LOG WHERE STATUS = 'COMPLETED') as total_distillations
FROM DUAL
"""
        
        success, output = self.execute_sql(sql)
        
        if success:
            # Parse the output
            lines = output.split('\n')
            for i, line in enumerate(lines):
                if '___' in line and 'TOTAL_CONCEPTS' in lines[i-1]:
                    if i + 1 < len(lines):
                        data_line = lines[i + 1].strip()
                        parts = data_line.split()
                        if len(parts) >= 5:
                            try:
                                return {
                                    'total_concepts': int(parts[0]),
                                    'validated_concepts': int(parts[1]),
                                    'pending_concepts': int(parts[2]),
                                    'total_relationships': int(parts[3]),
                                    'total_distillations': int(parts[4])
                                }
                            except (ValueError, IndexError):
                                pass
        
        return {}
    
    def get_graph_metrics(self) -> Dict[str, Any]:
        """
        Get knowledge graph metrics
        
        Returns:
            Graph metrics dictionary
        """
        # Use direct SQL queries
        sql = """
SELECT 
    (SELECT COUNT(*) FROM KNOWLEDGE_GRAPH) as total_relationships,
    (SELECT COUNT(DISTINCT SOURCE_CONCEPT_ID) FROM KNOWLEDGE_GRAPH) as concepts_with_relationships,
    (SELECT AVG(RELATIONSHIP_STRENGTH) FROM KNOWLEDGE_GRAPH) as avg_relationship_strength
FROM DUAL
"""
        
        success, output = self.execute_sql(sql)
        
        if success:
            lines = output.split('\n')
            for i, line in enumerate(lines):
                if '___' in line and 'TOTAL_RELATIONSHIPS' in lines[i-1]:
                    if i + 1 < len(lines):
                        data_line = lines[i + 1].strip()
                        parts = data_line.split()
                        if len(parts) >= 3:
                            try:
                                return {
                                    'total_relationships': int(parts[0]),
                                    'concepts_with_relationships': int(parts[1]),
                                    'avg_relationship_strength': float(parts[2])
                                }
                            except (ValueError, IndexError):
                                pass
        
        return {}
    
    def get_version_history(self, concept_id: int) -> List[Dict[str, Any]]:
        """
        Get concept version history
        
        Args:
            concept_id: Concept ID
            
        Returns:
            List of version dictionaries
        """
        # Use direct SQL query
        sql = f"""
SELECT VERSION_ID, TITLE, CHANGE_SUMMARY, TO_CHAR(VERSIONED_AT, 'YYYY-MM-DD HH24:MI:SS') as VERSIONED_AT
FROM KNOWLEDGE_VERSIONS
WHERE CONCEPT_ID = {concept_id}
ORDER BY VERSIONED_AT DESC
"""
        
        success, output = self.execute_sql(sql)
        
        versions = []
        if success:
            lines = output.split('\n')
            for i, line in enumerate(lines):
                if '___' in line and 'VERSION_ID' in lines[i-1]:
                    # Found separator, parse data lines
                    j = i + 1
                    while j < len(lines) and lines[j].strip() and '___' not in lines[j]:
                        data_line = lines[j].strip()
                        parts = data_line.split()
                        if len(parts) >= 2:
                            try:
                                versions.append({
                                    'version_id': int(parts[0]),
                                    'title': ' '.join(parts[1:-1]) if len(parts) > 2 else parts[1],
                                    'change_summary': parts[-1] if len(parts) > 2 else None,
                                    'versioned_at': parts[-1] if len(parts) <= 2 else parts[-1]
                                })
                            except (ValueError, IndexError):
                                pass
                        j += 1
                    break
        
        return versions


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

if __name__ == "__main__":
    # Initialize API
    kb = KnowledgeBaseAPI()
    
    print("=" * 80)
    print("Oracle Knowledge Base Python API - Usage Examples")
    print("=" * 80)
    
    # Example 1: Create a knowledge concept
    print("\n1. Creating a knowledge concept...")
    try:
        concept_id = kb.create_concept(
            concept_name="Oracle Property Graph Best Practices",
            concept_type="RULE",
            category="Database",
            title="Oracle 26ai Property Graph Design Rules",
            description="Best practices for designing Property Graphs in Oracle 26ai",
            content="""
# Oracle Property Graph Best Practices

1. **Isolation First**: Test in Python without DB access before executing DDL
2. **File Splitting**: Break complex SQL into separate files
3. **Verification After Each Step**: Confirm success before proceeding
4. **Preserve Existing Data**: New tables operate independently
            """,
            source_type="MANUAL",
            tags=["oracle", "property-graph", "best-practices"],
            confidence=0.95
        )
        print(f"   ✅ Created concept ID: {concept_id}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Example 2: Create a relationship
    print("\n2. Creating a relationship...")
    try:
        rel_id = kb.create_relationship(
            source_concept_id=1,
            target_concept_id=2,
            relationship_type="SUPPORTS",
            strength=0.9
        )
        print(f"   ✅ Created relationship ID: {rel_id}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Example 3: Semantic search
    print("\n3. Performing semantic search...")
    try:
        results = kb.semantic_search(
            query_text="Oracle database best practices",
            limit=5,
            min_confidence=0.5
        )
        print(f"   ✅ Found {len(results)} results")
        for r in results[:3]:
            print(f"      - {r.get('title', 'No title')}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Example 4: Get statistics
    print("\n4. Getting knowledge base statistics...")
    try:
        stats = kb.get_statistics()
        print(f"   ✅ Statistics: {json.dumps(stats, indent=2)}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print("\n" + "=" * 80)
    print("Examples completed!")
    print("=" * 80)
