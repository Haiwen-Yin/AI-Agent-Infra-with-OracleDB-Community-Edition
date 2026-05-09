#!/usr/bin/env python3
"""
Oracle Memory System v1.0.0 - Knowledge Base Test Suite
============================================================================
Description: Comprehensive test suite for Knowledge Base functionality
Version: 1.0.0-KB-TEST
Author: Haiwen Yin (胖头鱼 🐟)
Date: 2026-05-09
============================================================================
"""

import json
import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from knowledge_base_api import KnowledgeBaseAPI

class KnowledgeBaseTester:
    """Comprehensive test suite for Knowledge Base"""
    
    def __init__(self):
        self.kb = KnowledgeBaseAPI()
        self.results = []
        self.test_count = 0
        self.pass_count = 0
        self.fail_count = 0
    
    def add_result(self, test_name: str, status: str, message: str = ""):
        """Record test result"""
        self.test_count += 1
        if status == "PASS":
            self.pass_count += 1
        else:
            self.fail_count += 1
        
        self.results.append({
            'test_name': test_name,
            'status': status,
            'message': message
        })
        
        print(f"  {status}: {test_name} - {message}")
    
    def test_concept_operations(self):
        """Test 1: Knowledge Concept CRUD operations"""
        print("\n📚 Test 1: Knowledge Concept Operations")
        print("-" * 60)
        
        try:
            # Create concept
            concept_id = self.kb.create_concept(
                concept_name="Test Concept",
                concept_type="FACT",
                category="Testing",
                title="Test Knowledge Concept",
                description="This is a test concept for validation",
                content="Test content for knowledge base validation",
                source_type="MANUAL",
                tags=["test", "validation"],
                confidence=0.9
            )
            self.add_result("Create Concept", "PASS", f"Created ID: {concept_id}")
            
            # Get concept
            concept = self.kb.get_concept(concept_id)
            if concept.get('concept_id') == concept_id:
                self.add_result("Get Concept", "PASS", "Retrieved successfully")
            else:
                self.add_result("Get Concept", "FAIL", "Concept data mismatch")
            
            # Update concept
            success = self.kb.update_concept(
                concept_id,
                title="Updated Test Concept",
                change_summary="Updated for testing",
                change_reason="Unit test"
            )
            if success:
                self.add_result("Update Concept", "PASS", "Updated successfully")
            else:
                self.add_result("Update Concept", "FAIL", "Update failed")
            
            # Validate concept
            success = self.kb.validate_concept(concept_id, "VALIDATED", 0.95)
            if success:
                self.add_result("Validate Concept", "PASS", "Validated successfully")
            else:
                self.add_result("Validate Concept", "FAIL", "Validation failed")
            
            # Get version history
            versions = self.kb.get_version_history(concept_id)
            if isinstance(versions, list):
                self.add_result("Version History", "PASS", f"Found {len(versions)} versions")
            else:
                self.add_result("Version History", "FAIL", "Failed to get versions")
            
            return concept_id
            
        except Exception as e:
            self.add_result("Concept Operations", "FAIL", str(e))
            return None
    
    def test_relationship_operations(self):
        """Test 2: Knowledge Graph relationship operations"""
        print("\n🔗 Test 2: Knowledge Graph Operations")
        print("-" * 60)
        
        try:
            # Create two concepts for testing
            concept1_id = self.kb.create_concept(
                concept_name="Source Concept",
                concept_type="FACT",
                category="Testing",
                title="Source for Relationship Test",
                description="Source concept",
                content="Source content",
                tags=["test"]
            )
            
            concept2_id = self.kb.create_concept(
                concept_name="Target Concept",
                concept_type="FACT",
                category="Testing",
                title="Target for Relationship Test",
                description="Target concept",
                content="Target content",
                tags=["test"]
            )
            
            self.add_result("Create Test Concepts", "PASS", f"Created IDs: {concept1_id}, {concept2_id}")
            
            # Create relationship
            rel_id = self.kb.create_relationship(
                source_concept_id=concept1_id,
                target_concept_id=concept2_id,
                relationship_type="SUPPORTS",
                strength=0.85
            )
            self.add_result("Create Relationship", "PASS", f"Created relationship ID: {rel_id}")
            
            # Get relationships
            relationships = self.kb.get_relationships(concept1_id, "OUTGOING")
            if isinstance(relationships, list) and len(relationships) > 0:
                self.add_result("Get Relationships", "PASS", f"Found {len(relationships)} relationships")
            else:
                self.add_result("Get Relationships", "FAIL", "No relationships found")
            
            # Traverse graph
            traversal = self.kb.traverse_graph(concept1_id, 2)
            if isinstance(traversal, list):
                self.add_result("Traverse Graph", "PASS", f"Traversed {len(traversal)} paths")
            else:
                self.add_result("Traverse Graph", "FAIL", "Traversal failed")
            
            return concept1_id, concept2_id
            
        except Exception as e:
            self.add_result("Relationship Operations", "FAIL", str(e))
            return None, None
    
    def test_semantic_search(self):
        """Test 3: Semantic search functionality"""
        print("\n🔍 Test 3: Semantic Search")
        print("-" * 60)
        
        try:
            # Create some test concepts with embeddings
            concepts = []
            for i in range(5):
                concept_id = self.kb.create_concept(
                    concept_name=f"Search Test Concept {i}",
                    concept_type="FACT",
                    category="Search Testing",
                    title=f"Test Concept {i} for Search",
                    description=f"Description for search test {i}",
                    content=f"Content about topic {i} for testing search functionality",
                    tags=["search-test"]
                )
                concepts.append(concept_id)
            
            self.add_result("Create Search Concepts", "PASS", f"Created {len(concepts)} concepts")
            
            # Perform semantic search
            results = self.kb.semantic_search(
                query_text="test concept for search",
                limit=5,
                min_confidence=0.3
            )
            
            if isinstance(results, list) and len(results) > 0:
                self.add_result("Semantic Search", "PASS", f"Found {len(results)} results")
            else:
                self.add_result("Semantic Search", "FAIL", "No search results")
            
            return concepts
            
        except Exception as e:
            self.add_result("Semantic Search", "FAIL", str(e))
            return []
    
    def test_statistics(self):
        """Test 4: Statistics and monitoring"""
        print("\n📊 Test 4: Statistics and Monitoring")
        print("-" * 60)
        
        try:
            # Get KB statistics
            stats = self.kb.get_statistics()
            if isinstance(stats, dict) and 'total_concepts' in stats:
                self.add_result("KB Statistics", "PASS", 
                              f"Total concepts: {stats.get('total_concepts', 0)}")
            else:
                self.add_result("KB Statistics", "FAIL", "Failed to get statistics")
            
            # Get graph metrics
            metrics = self.kb.get_graph_metrics()
            if isinstance(metrics, dict):
                self.add_result("Graph Metrics", "PASS", 
                              f"Avg relationships: {metrics.get('avg_relationships_per_concept', 0):.2f}")
            else:
                self.add_result("Graph Metrics", "FAIL", "Failed to get metrics")
            
        except Exception as e:
            self.add_result("Statistics", "FAIL", str(e))
    
    def generate_report(self):
        """Generate test report"""
        print("\n" + "=" * 80)
        print("📊 KNOWLEDGE BASE TEST REPORT")
        print("=" * 80)
        
        print(f"\nTest Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Total Tests: {self.test_count}")
        print(f"Passed: {self.pass_count} ✅")
        print(f"Failed: {self.fail_count} ❌")
        
        if self.fail_count > 0:
            print("\n❌ FAILED TESTS:")
            for result in self.results:
                if result['status'] == 'FAIL':
                    print(f"  - {result['test_name']}: {result['message']}")
        
        # Overall status
        if self.fail_count == 0:
            print("\n✅ OVERALL STATUS: ALL TESTS PASSED")
        else:
            print(f"\n⚠️ OVERALL STATUS: {self.fail_count} TESTS FAILED")
        
        print("\n" + "=" * 80)

# Main execution
if __name__ == "__main__":
    tester = KnowledgeBaseTester()
    
    print("\n🚀 Starting Knowledge Base Tests...")
    print("=" * 80)
    
    # Run all tests
    tester.test_concept_operations()
    tester.test_relationship_operations()
    tester.test_semantic_search()
    tester.test_statistics()
    
    # Generate report
    tester.generate_report()
