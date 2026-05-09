"""
Oracle AI Database Memory System v1.0.0 - Final Python API (SQLcl Version)
Author: 胖头鱼 🐟 (Haiwen Yin)
Version: v1.0.0 Production Release
Last Updated: 2024-12-19

Python API using SQLcl - matches actual database schema
"""

import json
import time
import hashlib
import logging
import subprocess
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import threading

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
SQLCL_PATH = "/root/sqlcl/sqlcl/bin/sql"
DEFAULT_DB_CONNECTION = "openclaw/hermes@//10.10.10.130:1521/openclaw"


@dataclass
class DatabaseConfig:
    """Database configuration"""
    db_connection: str = DEFAULT_DB_CONNECTION
    sqlcl_path: str = SQLCL_PATH
    enable_cache: bool = True
    cache_ttl: int = 300


class QueryCache:
    """In-memory query cache with TTL"""
    
    def __init__(self, max_size: int = 1000, ttl: int = 300):
        self.max_size = max_size
        self.ttl = ttl
        self.cache = {}
        self.access_times = {}
        self._lock = threading.Lock()
        
    def _make_key(self, sql: str) -> str:
        """Generate cache key"""
        return hashlib.md5(sql.encode()).hexdigest()
        
    def get(self, sql: str) -> Optional[str]:
        """Get cached result"""
        key = self._make_key(sql)
        
        with self._lock:
            if key in self.cache:
                if time.time() - self.access_times[key] < self.ttl:
                    return self.cache[key]
                else:
                    del self.cache[key]
                    del self.access_times[key]
                    
        return None
        
    def set(self, sql: str, result: str):
        """Cache result"""
        key = self._make_key(sql)
        
        with self._lock:
            if len(self.cache) >= self.max_size:
                oldest_key = min(self.access_times, key=self.access_times.get)
                del self.cache[oldest_key]
                del self.access_times[oldest_key]
                
            self.cache[key] = result
            self.access_times[key] = time.time()
            
    def clear(self):
        """Clear cache"""
        with self._lock:
            self.cache.clear()
            self.access_times.clear()


class OracleMemorySystem:
    """Optimized Oracle Memory System API using SQLcl"""
    
    def __init__(self, config: DatabaseConfig = None):
        self.config = config or DatabaseConfig()
        self.cache = QueryCache(max_size=1000, ttl=self.config.cache_ttl) if self.config.enable_cache else None
        
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        
    def close(self):
        """Close resources"""
        if self.cache:
            self.cache.clear()
            
    def execute_sql(self, sql: str, fetch: bool = True) -> Tuple[bool, str]:
        """Execute SQL via SQLcl"""
        # Check cache for SELECT queries
        if self.cache and fetch and sql.strip().upper().startswith("SELECT"):
            cached = self.cache.get(sql)
            if cached is not None:
                return (True, cached)
                
        cmd = f'echo "{sql}" | {self.config.sqlcl_path} {self.config.db_connection}'
        
        try:
            process = subprocess.run(
                ['bash', '-c', cmd],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            output = process.stdout + process.stderr
            
            # Cache SELECT results
            if self.cache and fetch and sql.strip().upper().startswith("SELECT"):
                self.cache.set(sql, output)
                
            return (process.returncode == 0, output)
            
        except subprocess.TimeoutExpired:
            return (False, "SQL execution timeout")
        except Exception as e:
            return (False, str(e))
            
    def _parse_output(self, output: str, expected_cols: int) -> List[Dict]:
        """Parse SQLcl tabular output"""
        results = []
        lines = output.strip().split('\n')
        
        header_idx = -1
        for i, line in enumerate(lines):
            # Find header line (contains column names)
            if any(col in line.lower() for col in ['concept_id', 'relationship_id', 'memory_id', 'tag_id']):
                header_idx = i
                break
                
        if header_idx >= 0:
            # Parse data lines after header
            for j in range(header_idx + 1, len(lines)):
                if lines[j].strip() == '' or '---' in lines[j] or 'rows selected' in lines[j]:
                    break
                values = lines[j].split('|')
                if len(values) >= expected_cols:
                    results.append(values)
                    
        return results
        
    # ========================================================================
    # Knowledge Concept Operations
    # ========================================================================
    
    def create_concept(
        self,
        concept_name: str,
        concept_type: str,
        description: str = None,
        category: str = None,
        tags: List[str] = None,
        metadata: Dict = None,
        confidence: float = 0.8
    ) -> int:
        """Create new knowledge concept"""
        desc_value = f"'{description.replace(chr(39), chr(39)+chr(39))}'" if description else 'NULL'
        cat_value = f"'{category}'" if category else 'NULL'
        tags_json = json.dumps(tags) if tags else None
        metadata_json = json.dumps(metadata) if metadata else None
        
        sql = f"""
            INSERT INTO KNOWLEDGE_CONCEPTS 
            (CONCEPT_ID, CONCEPT_NAME, CONCEPT_TYPE, DESCRIPTION, CATEGORY, 
             TAGS, METADATA, CONFIDENCE, VALIDATION_STATUS, VERSION, IS_CURRENT)
            VALUES (
                (SELECT NVL(MAX(CONCEPT_ID), 0) + 1 FROM KNOWLEDGE_CONCEPTS),
                '{concept_name.replace(chr(39), chr(39)+chr(39))}',
                '{concept_type}',
                {desc_value},
                {cat_value},
                '{tags_json}',
                '{metadata_json}',
                {confidence},
                'PENDING',
                1,
                'Y'
            )
        """
        
        success, output = self.execute_sql(sql, fetch=False)
        
        if success:
            # Get the ID
            id_sql = "SELECT MAX(CONCEPT_ID) FROM KNOWLEDGE_CONCEPTS"
            success, id_output = self.execute_sql(id_sql)
            if success:
                lines = id_output.strip().split('\n')
                for line in lines:
                    if line.strip().isdigit():
                        return int(line.strip())
                        
        raise Exception(f"Failed to create concept: {output}")
        
    def get_concept(self, concept_id: int) -> Dict:
        """Get concept by ID"""
        sql = f"""
            SELECT CONCEPT_ID, CONCEPT_NAME, CONCEPT_TYPE, DESCRIPTION, CATEGORY,
                   TAGS, METADATA, CONFIDENCE, VALIDATION_STATUS,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') as CREATED_AT,
                   TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') as UPDATED_AT
            FROM KNOWLEDGE_CONCEPTS
            WHERE CONCEPT_ID = {concept_id}
        """
        
        success, output = self.execute_sql(sql)
        
        if not success:
            return None
            
        results = self._parse_output(output, 11)
        if results:
            values = results[0]
            try:
                return {
                    'concept_id': int(values[0].strip()),
                    'concept_name': values[1].strip(),
                    'concept_type': values[2].strip(),
                    'description': values[3].strip(),
                    'category': values[4].strip(),
                    'tags': json.loads(values[5].strip()) if values[5].strip() and values[5].strip() != 'null' else [],
                    'metadata': json.loads(values[6].strip()) if values[6].strip() and values[6].strip() != 'null' else {},
                    'confidence': float(values[7].strip()) if values[7].strip() else 0.8,
                    'validation_status': values[8].strip(),
                    'created_at': values[9].strip(),
                    'updated_at': values[10].strip()
                }
            except (ValueError, json.JSONDecodeError) as e:
                logger.error(f"Error parsing concept: {e}")
                
        return None
        
    def update_concept(
        self,
        concept_id: int,
        concept_name: str = None,
        concept_type: str = None,
        description: str = None,
        category: str = None,
        tags: List[str] = None,
        metadata: Dict = None
    ) -> bool:
        """Update concept"""
        updates = []
        
        if concept_name is not None:
            updates.append(f"CONCEPT_NAME = '{concept_name.replace(chr(39), chr(39)+chr(39))}'")
        if concept_type is not None:
            updates.append(f"CONCEPT_TYPE = '{concept_type}'")
        if description is not None:
            updates.append(f"DESCRIPTION = '{description.replace(chr(39), chr(39)+chr(39))}'")
        if category is not None:
            updates.append(f"CATEGORY = '{category}'")
        if tags is not None:
            updates.append(f"TAGS = '{json.dumps(tags)}'")
        if metadata is not None:
            updates.append(f"METADATA = '{json.dumps(metadata)}'")
            
        if not updates:
            return False
            
        updates.append("UPDATED_AT = SYSTIMESTAMP")
        
        sql = f"UPDATE KNOWLEDGE_CONCEPTS SET {', '.join(updates)} WHERE CONCEPT_ID = {concept_id}"
        
        success, output = self.execute_sql(sql, fetch=False)
        
        # Clear cache
        if self.cache:
            self.cache.clear()
            
        return success
        
    def delete_concept(self, concept_id: int) -> bool:
        """Delete concept"""
        sql = f"DELETE FROM KNOWLEDGE_CONCEPTS WHERE CONCEPT_ID = {concept_id}"
        
        success, output = self.execute_sql(sql, fetch=False)
        
        # Clear cache
        if self.cache:
            self.cache.clear()
            
        return success
        
    def get_concepts_by_type(
        self,
        concept_type: str,
        limit: int = 100
    ) -> List[Dict]:
        """Get concepts by type"""
        sql = f"""
            SELECT CONCEPT_ID, CONCEPT_NAME, CONCEPT_TYPE, DESCRIPTION, CATEGORY
            FROM KNOWLEDGE_CONCEPTS
            WHERE CONCEPT_TYPE = '{concept_type}'
            ORDER BY CREATED_AT DESC
            FETCH FIRST {limit} ROWS ONLY
        """
        
        success, output = self.execute_sql(sql)
        
        if not success:
            return []
            
        results = self._parse_output(output, 5)
        concepts = []
        for values in results:
            try:
                concepts.append({
                    'concept_id': int(values[0].strip()),
                    'concept_name': values[1].strip(),
                    'concept_type': values[2].strip(),
                    'description': values[3].strip(),
                    'category': values[4].strip()
                })
            except ValueError:
                pass
                
        return concepts
        
    # ========================================================================
    # Knowledge Graph Operations
    # ========================================================================
    
    def create_relationship(
        self,
        source_concept_id: int,
        target_concept_id: int,
        relationship_type: str,
        strength: float = 1.0,
        properties: Dict = None,
        confidence: float = 0.8
    ) -> int:
        """Create new relationship in knowledge graph"""
        properties_json = json.dumps(properties) if properties else None
        
        sql = f"""
            INSERT INTO KNOWLEDGE_GRAPH 
            (RELATIONSHIP_ID, SOURCE_CONCEPT_ID, TARGET_CONCEPT_ID, RELATIONSHIP_TYPE,
             RELATIONSHIP_STRENGTH, PROPERTIES, CONFIDENCE, SOURCE_TYPE)
            VALUES (
                (SELECT NVL(MAX(RELATIONSHIP_ID), 0) + 1 FROM KNOWLEDGE_GRAPH),
                {source_concept_id},
                {target_concept_id},
                '{relationship_type}',
                {strength},
                '{properties_json}',
                {confidence},
                'MANUAL'
            )
        """
        
        success, output = self.execute_sql(sql, fetch=False)
        
        if success:
            # Get the ID
            id_sql = "SELECT MAX(RELATIONSHIP_ID) FROM KNOWLEDGE_GRAPH"
            success, id_output = self.execute_sql(id_sql)
            if success:
                lines = id_output.strip().split('\n')
                for line in lines:
                    if line.strip().isdigit():
                        return int(line.strip())
                        
        raise Exception(f"Failed to create relationship: {output}")
        
    def get_relationships(
        self,
        concept_id: int,
        direction: str = "both"
    ) -> List[Dict]:
        """Get relationships for concept"""
        if direction == "outgoing":
            where_clause = f"SOURCE_CONCEPT_ID = {concept_id}"
        elif direction == "incoming":
            where_clause = f"TARGET_CONCEPT_ID = {concept_id}"
        else:
            where_clause = f"(SOURCE_CONCEPT_ID = {concept_id} OR TARGET_CONCEPT_ID = {concept_id})"
            
        sql = f"""
            SELECT RELATIONSHIP_ID, SOURCE_CONCEPT_ID, TARGET_CONCEPT_ID,
                   RELATIONSHIP_TYPE, RELATIONSHIP_STRENGTH, PROPERTIES, CONFIDENCE
            FROM KNOWLEDGE_GRAPH
            WHERE {where_clause}
            ORDER BY CREATED_AT DESC
        """
        
        success, output = self.execute_sql(sql)
        
        if not success:
            return []
            
        results = self._parse_output(output, 7)
        relationships = []
        for values in results:
            try:
                relationships.append({
                    'relationship_id': int(values[0].strip()),
                    'source_concept_id': int(values[1].strip()),
                    'target_concept_id': int(values[2].strip()),
                    'relationship_type': values[3].strip(),
                    'strength': float(values[4].strip()) if values[4].strip() else 1.0,
                    'properties': json.loads(values[5].strip()) if values[5].strip() and values[5].strip() != 'null' else {},
                    'confidence': float(values[6].strip()) if values[6].strip() else 0.8
                })
            except (ValueError, json.JSONDecodeError):
                pass
                
        return relationships
        
    def delete_relationship(self, relationship_id: int) -> bool:
        """Delete relationship"""
        sql = f"DELETE FROM KNOWLEDGE_GRAPH WHERE RELATIONSHIP_ID = {relationship_id}"
        
        success, output = self.execute_sql(sql, fetch=False)
        
        # Clear cache
        if self.cache:
            self.cache.clear()
            
        return success
        
    # ========================================================================
    # Statistics and Metrics
    # ========================================================================
    
    def get_statistics(self) -> Dict:
        """Get system statistics"""
        sql = """
            SELECT 
                (SELECT COUNT(*) FROM KNOWLEDGE_CONCEPTS) AS total_concepts,
                (SELECT COUNT(*) FROM KNOWLEDGE_GRAPH) AS total_relationships,
                (SELECT COUNT(*) FROM KNOWLEDGE_TAGS) AS total_tags
            FROM DUAL
        """
        
        success, output = self.execute_sql(sql)
        
        if success:
            results = self._parse_output(output, 3)
            if results:
                try:
                    return {
                        'total_concepts': int(results[0][0].strip()),
                        'total_relationships': int(results[0][1].strip()),
                        'total_tags': int(results[0][2].strip())
                    }
                except ValueError:
                    pass
                    
        return {}
        
    def get_graph_metrics(self) -> Dict:
        """Get graph metrics"""
        sql = """
            SELECT 
                (SELECT COUNT(*) FROM KNOWLEDGE_CONCEPTS) AS total_concepts,
                (SELECT COUNT(*) FROM KNOWLEDGE_GRAPH) AS total_relationships,
                (SELECT NVL(AVG(cnt), 0) FROM (SELECT COUNT(*) AS cnt FROM KNOWLEDGE_GRAPH GROUP BY SOURCE_CONCEPT_ID)) AS avg_connections,
                (SELECT NVL(MAX(cnt), 0) FROM (SELECT COUNT(*) AS cnt FROM KNOWLEDGE_GRAPH GROUP BY SOURCE_CONCEPT_ID)) AS max_connections
            FROM DUAL
        """
        
        success, output = self.execute_sql(sql)
        
        if success:
            results = self._parse_output(output, 4)
            if results:
                try:
                    return {
                        'total_concepts': int(results[0][0].strip()),
                        'total_relationships': int(results[0][1].strip()),
                        'avg_connections': float(results[0][2].strip()),
                        'max_connections': int(results[0][3].strip())
                    }
                except ValueError:
                    pass
                    
        return {}


# ============================================================================
# Usage Example
# ============================================================================

if __name__ == "__main__":
    # Initialize system
    system = OracleMemorySystem()
    
    # Test connection
    success, output = system.execute_sql("SELECT COUNT(*) FROM KNOWLEDGE_CONCEPTS")
    print(f"Connection test: {success}")
    
    # Get statistics
    stats = system.get_statistics()
    print(f"Statistics: {stats}")
    
    # Get graph metrics
    metrics = system.get_graph_metrics()
    print(f"Graph metrics: {metrics}")
    
    # Cleanup
    system.close()
