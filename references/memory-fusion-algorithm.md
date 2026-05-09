# Memory Fusion Algorithm Design Document

**Version**: v0.4.3 (Optimization Update)  
**Author**: Haiwen Yin (胖头鱼 🐟)  
**Date**: 2026-05-08  

---

## Problem Statement

In multi-turn agent conversations, the same information is often stored multiple times:
1. Agent stores "API endpoint for user authentication" in turn 3
2. Same concept mentioned again with slightly different wording in turn 7
3. Result: duplicate memories consuming storage and reducing retrieval accuracy

---

## Algorithm Overview

### Memory Fusion Strategy

```
┌─────────────────────────────────────────────────────────────┐
│                    Multi-Turn Conversation                   │
└─────────────────────────────────────────────────────────────┘
                          ↓
    ┌─────────────────────────────────────────┐
    │         MEMORY FUSION ENGINE             │
    │                                         │
    │  1. Content Similarity Check            │
    │     (semantic similarity > 85%)         │
    │  2. Temporal Proximity Analysis        │
    │     (within same conversation session)   │
    │  3. Conflict Resolution                │
    │     (latest version wins with merge)     │
    │  4. Deduplication Action               │
    │     (merge or delete duplicate)         │
    └─────────────────────────────────────────┘
                          ↓
              ┌───────────────┐
              │   Oracle DB   │
              │ (Unified Memory)│
              └───────────────┘
```

---

## Core Components

### 1. Content Similarity Calculator

Uses semantic embeddings to compare memory content:

```python
class MemorySimilarityCalculator:
    """Calculate semantic similarity between two memories"""
    
    def __init__(self, embedding_model="text-embedding-bge-m3"):
        self.model = embedding_model
        self.similarity_threshold = 0.85  # 85% threshold for fusion
    
    def calculate_similarity(self, memory1: dict, memory2: dict) -> float:
        """Calculate semantic similarity score (0.0-1.0)"""
        
        # Get embeddings for both memories
        embedding1 = self._get_embedding(memory1['content'])
        embedding2 = self._get_embedding(memory2['content'])
        
        # Calculate cosine similarity
        dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
        norm1 = math.sqrt(sum(a**2 for a in embedding1))
        norm2 = math.sqrt(sum(b**2 for b in embedding2))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        similarity = dot_product / (norm1 * norm2)
        
        # Apply content type boost for same category
        if memory1.get('category') == memory2.get('category'):
            similarity = min(similarity + 0.1, 1.0)
        
        return max(0.0, min(1.0, similarity))  # Clamp to [0, 1]
    
    def _get_embedding(self, text: str) -> list:
        """Get embedding vector for text"""
        # Implementation depends on embedding provider
        pass
```

### 2. Memory Fusion Engine

Main logic for deciding when and how to merge memories:

```python
class MemoryFusionEngine:
    """Decides whether to fuse memories and performs the merge"""
    
    def __init__(self, cache_manager=None):
        self.similarity_calculator = MemorySimilarityCalculator()
        self.cache_manager = cache_manager
    
    def should_fuse_memories(self, memory1: dict, memory2: dict) -> bool:
        """Determine if two memories should be merged"""
        
        # Check 1: Content similarity above threshold
        similarity = self.similarity_calculator.calculate_similarity(memory1, memory2)
        if similarity < 0.85:
            return False
        
        # Check 2: Same category or related categories
        same_category = memory1.get('category') == memory2.get('category')
        
        # Check 3: Temporal proximity (within same conversation session)
        time_diff = abs(
            (memory2.get('created_at', 0) - memory1.get('created_at', 0)) / 1000
        )
        within_session = time_diff < 3600 * 24  # Within 24 hours
        
        return same_category and within_session
    
    def fuse_memories(self, primary: dict, secondary: dict) -> dict:
        """Merge two similar memories into one"""
        
        fusion_result = {
            'memory_id': primary['memory_id'],  # Keep primary ID
            'content': self._merge_content(primary, secondary),
            'category': primary.get('category'),
            'visibility': primary.get('visibility', 'SHARED'),
            'tags': self._merge_tags(primary, secondary),
            
            # Fusion metadata for audit trail
            'fused_from_ids': [secondary['memory_id']],
            'fusion_timestamp': datetime.now().isoformat(),
            'access_count': primary.get('access_count', 0) + 
                           secondary.get('access_count', 0),
        }
        
        # Update metadata with latest access time
        fusion_result['last_accessed'] = max(
            primary.get('last_accessed'), 
            secondary.get('last_accessed')
        )
        
        return fusion_result
    
    def _merge_content(self, memory1: dict, memory2: dict) -> str:
        """Smart content merging - combine complementary information"""
        
        # If one content is substring of another, keep longer version
        if memory1['content'] in memory2['content']:
            return memory2['content']
        elif memory2['content'] in memory1['content']:
            return memory1['content']
        
        # Otherwise concatenate with separator (prioritize primary)
        return f"{memory1['content']} | {memory2['content']}"
    
    def _merge_tags(self, memory1: dict, memory2: dict) -> str:
        """Merge tag arrays without duplicates"""
        
        import json
        
        try:
            tags1 = json.loads(memory1.get('tags', '[]')) if isinstance(memory1.get('tags'), str) else memory1.get('tags', [])
            tags2 = json.loads(memory2.get('tags', '[]')) if isinstance(memory2.get('tags'), str) else memory2.get('tags', [])
            
            merged_tags = list(dict.fromkeys(tags1 + tags2))  # Remove duplicates, preserve order
            return json.dumps(merged_tags)
        except (json.JSONDecodeError, TypeError):
            return memory1.get('tags', '[]')
```

### 3. Automated Fusion Trigger

Fusion should happen automatically during these operations:

```python
class MemoryManagerWithFusion:
    """Memory manager with automatic fusion capabilities"""
    
    def __init__(self, oracle_api, cache_manager=None):
        self.oracle_api = oracle_api
        self.fusion_engine = MemoryFusionEngine(cache_manager)
    
    def store_memory_with_fusion_check(self, memory_data: dict) -> str:
        """Store new memory and check for potential fusion candidates"""
        
        # Step 1: Store the new memory first
        new_memory_id = self.oracle_api.insert_memory(memory_data)
        
        # Step 2: Find similar existing memories within same session
        recent_memories = self._get_recent_memories(
            category=memory_data.get('category'),
            time_window_hours=24
        )
        
        for existing_memory in recent_memories:
            if self.fusion_engine.should_fuse_memories(
                memory_data, 
                existing_memory
            ):
                # Step 3: Fuse with the most similar one
                fusion_result = self.fusion_engine.fuse_memories(
                    primary=existing_memory,
                    secondary=memory_data
                )
                
                # Step 4: Update primary memory and delete duplicate
                self.oracle_api.update_memory(fusion_result)
                self.oracle_api.delete_memory(new_memory_id)
                
                logger.info(f"Fused memories: {existing_memory['id']} + {new_memory_id}")
                
                return existing_memory['memory_id']  # Return fused ID
        
        return new_memory_id
    
    def _get_recent_memories(self, category: str, time_window_hours: int) -> list:
        """Get recently created memories for comparison"""
        
        query = f"""
            SELECT * FROM MEMORIES 
            WHERE CATEGORY = :category 
              AND CREATED_AT > SYSTIMESTAMP - INTERVAL '{time_window_hours}' HOUR
            ORDER BY CREATED_AT DESC
        """
        
        # Execute query and return results
        pass
```

---

## Configuration Parameters

| Parameter | Default Value | Description | Recommended Range |
|-----------|---------------|-------------|-------------------|
| `similarity_threshold` | 0.85 | Minimum semantic similarity for fusion | 0.75 - 0.95 |
| `max_fusion_history` | 5 | Maximum number of memories in fusion chain | 3 - 10 |
| `fusion_cooldown_seconds` | 60 | Min time between consecutive fusions | 30 - 300 |
| `session_time_window_hours` | 24 | Time window for considering same-session memories | 12 - 72 |

---

## Performance Impact Assessment

### Before Fusion (No Optimization)
- **Storage Growth**: Linear with conversation turns (each mention = new memory)
- **Retrieval Accuracy**: Degraded by duplicate similar entries
- **Query Latency**: Higher due to more records to scan

### After Fusion Implementation
- **Storage Reduction**: 30-60% fewer duplicate entries
- **Retrieval Accuracy**: Improved (no conflicting duplicates)
- **Query Latency**: Lower (fewer records, better ranking)

### CPU Cost of Fusion Algorithm
```python
# Similarity calculation complexity: O(n*m) where n,m = embedding dimensions
# Typical overhead per fusion decision: ~2-5ms on modern hardware
# Acceptable for memory operations (< 100ms total API call budget)
```

---

## Integration with Cache Layer

Fusion should invalidate related cache entries immediately:

```python
def fuse_memories_with_cache_invalidation(self, primary_id, secondary_id):
    """Perform fusion and invalidate associated caches"""
    
    # Perform memory fusion (existing logic)
    fused_result = self.fuse_memories(primary_id, secondary_id)
    
    # Invalidate cache entries for both old memories
    if self.cache_manager:
        self.cache_manager.invalidate_memory(primary_id)
        self.cache_manager.invalidate_memory(secondary_id)
        
        # Cache the newly fused memory
        self.cache_manager.store_in_cache(fused_result['memory_id'], 
                                         fused_result, 
                                         'SHARED')
    
    return fused_result
```

---

## Monitoring Fusion Metrics

Track fusion effectiveness over time:

| Metric | Calculation | Target |
|--------|-------------|--------|
| Fusion Rate | Fusions / New Memories Created | 20-40% (indicates good deduplication) |
| Average Chain Length | Mean memories fused together | < 3 (too many = over-merging) |
| Post-Fusion Access Count | Sum of accesses on fused memory | Should exceed individual counts |

---

*Document Version: v0.4.3 | Last Updated: 2026-05-08*
