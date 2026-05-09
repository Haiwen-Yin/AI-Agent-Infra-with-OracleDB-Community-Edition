"""
Oracle AI Database Memory System v1.0.0 - Batch Operations (SQLcl Version)
Author: 胖头鱼 🐟 (Haiwen Yin)
Version: v1.0.0 Production Release
Last Updated: 2024-12-19

Batch operations using SQLcl for high-performance data loading
"""

import json
import time
import logging
import subprocess
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import threading

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
SQLCL_PATH = "/root/sqlcl/sqlcl/bin/sql"
DEFAULT_DB_CONNECTION = "openclaw/hermes@//10.10.10.130:1521/openclaw"


@dataclass
class BatchConfig:
    """Batch operation configuration"""
    batch_size: int = 50
    timeout: int = 120
    retry_count: int = 3
    retry_delay: int = 2


class BatchProcessor:
    """High-performance batch processor using SQLcl"""
    
    def __init__(self, db_connection: str = None, config: BatchConfig = None):
        self.db_connection = db_connection or DEFAULT_DB_CONNECTION
        self.config = config or BatchConfig()
        self._lock = threading.Lock()
        self._stats = {
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'start_time': None,
            'end_time': None
        }
        
    def execute_sql(self, sql: str) -> Tuple[bool, str]:
        """Execute SQL via SQLcl"""
        cmd = f'echo "{sql}" | {SQLCL_PATH} {self.db_connection}'
        
        try:
            process = subprocess.run(
                ['bash', '-c', cmd],
                capture_output=True,
                text=True,
                timeout=self.config.timeout
            )
            
            output = process.stdout + process.stderr
            return (process.returncode == 0, output)
            
        except subprocess.TimeoutExpired:
            return (False, "SQL execution timeout")
        except Exception as e:
            return (False, str(e))
            
    def batch_insert_memories(
        self,
        memories_data: List[Dict]
    ) -> Dict[str, Any]:
        """Batch insert memories"""
        self._stats['start_time'] = time.time()
        self._stats['total_processed'] = len(memories_data)
        
        successful = 0
        failed = 0
        errors = []
        
        # Process in batches
        for i in range(0, len(memories_data), self.config.batch_size):
            batch = memories_data[i:i + self.config.batch_size]
            
            # Build INSERT statement for batch
            values_list = []
            for data in batch:
                content = data.get('content', '').replace("'", "''")
                memory_type = data.get('memory_type', 'experience')
                tags = json.dumps(data.get('tags', []))
                metadata = json.dumps(data.get('metadata', {}))
                
                values_list.append(
                    f"('{content}', '{memory_type}', '{tags}', '{metadata}', 'bge-m3', 'active')"
                )
                
            sql = f"""
                INSERT INTO memories (content, memory_type, tags, metadata, embedding_model, status)
                VALUES {', '.join(values_list)}
            """
            
            # Execute with retry
            for attempt in range(self.config.retry_count):
                success, output = self.execute_sql(sql)
                
                if success:
                    successful += len(batch)
                    logger.info(f"Batch {i//self.config.batch_size + 1} committed: {len(batch)} rows")
                    break
                else:
                    if attempt < self.config.retry_count - 1:
                        logger.warning(f"Batch {i//self.config.batch_size + 1} failed (attempt {attempt + 1}): {output[:100]}")
                        time.sleep(self.config.retry_delay)
                    else:
                        logger.error(f"Batch {i//self.config.batch_size + 1} failed permanently: {output[:100]}")
                        failed += len(batch)
                        errors.append(output[:200])
                        
        self._stats['end_time'] = time.time()
        self._stats['successful'] = successful
        self._stats['failed'] = failed
        
        duration = self._stats['end_time'] - self._stats['start_time']
        
        return {
            'total_processed': len(memories_data),
            'successful': successful,
            'failed': failed,
            'errors': errors,
            'duration_seconds': duration,
            'rows_per_second': len(memories_data) / duration if duration > 0 else 0
        }
        
    def batch_insert_concepts(
        self,
        concepts_data: List[Dict]
    ) -> Dict[str, Any]:
        """Batch insert concepts"""
        self._stats['start_time'] = time.time()
        self._stats['total_processed'] = len(concepts_data)
        
        successful = 0
        failed = 0
        errors = []
        
        # Process in batches
        for i in range(0, len(concepts_data), self.config.batch_size):
            batch = concepts_data[i:i + self.config.batch_size]
            
            # Build INSERT statement for batch
            values_list = []
            for data in batch:
                name = data.get('name', '').replace("'", "''")
                concept_type = data.get('concept_type', 'concept')
                description = data.get('description', '').replace("'", "''") if data.get('description') else 'NULL'
                properties = json.dumps(data.get('properties', {}))
                tags = json.dumps(data.get('tags', []))
                
                if description == 'NULL':
                    values_list.append(
                        f"('{name}', '{concept_type}', NULL, '{properties}', '{tags}', 'bge-m3', 'active')"
                    )
                else:
                    values_list.append(
                        f"('{name}', '{concept_type}', '{description}', '{properties}', '{tags}', 'bge-m3', 'active')"
                    )
                    
            sql = f"""
                INSERT INTO knowledge_concepts (name, concept_type, description, properties, tags, embedding_model, status)
                VALUES {', '.join(values_list)}
            """
            
            # Execute with retry
            for attempt in range(self.config.retry_count):
                success, output = self.execute_sql(sql)
                
                if success:
                    successful += len(batch)
                    logger.info(f"Batch {i//self.config.batch_size + 1} committed: {len(batch)} rows")
                    break
                else:
                    if attempt < self.config.retry_count - 1:
                        logger.warning(f"Batch {i//self.config.batch_size + 1} failed (attempt {attempt + 1})")
                        time.sleep(self.config.retry_delay)
                    else:
                        logger.error(f"Batch {i//self.config.batch_size + 1} failed permanently")
                        failed += len(batch)
                        errors.append(output[:200])
                        
        self._stats['end_time'] = time.time()
        self._stats['successful'] = successful
        self._stats['failed'] = failed
        
        duration = self._stats['end_time'] - self._stats['start_time']
        
        return {
            'total_processed': len(concepts_data),
            'successful': successful,
            'failed': failed,
            'errors': errors,
            'duration_seconds': duration,
            'rows_per_second': len(concepts_data) / duration if duration > 0 else 0
        }
        
    def get_statistics(self) -> Dict[str, Any]:
        """Get batch operation statistics"""
        return self._stats.copy()


# ============================================================================
# Usage Examples
# ============================================================================

if __name__ == "__main__":
    # Create batch processor
    processor = BatchProcessor()
    
    # Example: Batch insert memories
    memories = [
        {
            'content': f'Batch memory {i}',
            'memory_type': 'observation',
            'tags': ['batch', 'test'],
            'metadata': {'index': i}
        }
        for i in range(100)
    ]
    
    print("Starting batch insert...")
    result = processor.batch_insert_memories(memories)
    print(f"Batch insert completed: {result}")
    
    # Example: Batch insert concepts
    concepts = [
        {
            'name': f'Batch Concept {i}',
            'concept_type': 'technology',
            'description': f'Test concept {i}',
            'properties': {'version': '1.0.0'},
            'tags': ['batch', 'test']
        }
        for i in range(50)
    ]
    
    print("\nStarting batch concept insert...")
    result = processor.batch_insert_concepts(concepts)
    print(f"Batch concept insert completed: {result}")
