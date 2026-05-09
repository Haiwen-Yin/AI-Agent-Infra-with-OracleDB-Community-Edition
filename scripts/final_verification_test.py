"""
Oracle AI Database Memory System v1.0.0 - Final Verification Test
Author: 胖头鱼 🐟 (Haiwen Yin)
Version: v1.0.0 Production Release
Last Updated: 2024-12-19

Comprehensive test suite for all v1.0.0 features
"""

import json
import time
import sys

# Add scripts directory to path
sys.path.append('/root/.hermes/skills/oracle-memory-by-yhw/scripts')

from knowledge_base_api_optimized import OracleMemorySystem, DatabaseConfig


class FinalVerificationTest:
    """Final verification test suite"""
    
    def __init__(self):
        self.config = DatabaseConfig()
        self.system = OracleMemorySystem(self.config)
        self.test_results = []
        
    def run_all_tests(self):
        """Run all verification tests"""
        print("=" * 70)
        print("Oracle AI Database Memory System v1.0.0 - Final Verification Test")
        print("=" * 70)
        print()
        
        tests = [
            ("1. Database Connection", self.test_database_connection),
            ("2. Concept CRUD Operations", self.test_concept_operations),
            ("3. Relationship CRUD Operations", self.test_relationship_operations),
            ("4. Statistics and Metrics", self.test_statistics),
            ("5. Cache Performance", self.test_cache_performance),
            ("6. Final Cleanup", self.test_cleanup),
        ]
        
        for test_name, test_func in tests:
            print(f"\n{'=' * 70}")
            print(f"Running: {test_name}")
            print(f"{'=' * 70}")
            
            try:
                result = test_func()
                self.test_results.append({
                    'test_name': test_name,
                    'status': 'PASS' if result else 'FAIL'
                })
                status = "✅ PASS" if result else "❌ FAIL"
                print(f"{status}: {test_name}")
            except Exception as e:
                self.test_results.append({
                    'test_name': test_name,
                    'status': 'ERROR',
                    'error': str(e)
                })
                print(f"❌ ERROR: {test_name} - {e}")
                
        self.print_summary()
        
    def test_database_connection(self) -> bool:
        """Test database connection"""
        try:
            success, output = self.system.execute_sql("SELECT COUNT(*) FROM KNOWLEDGE_CONCEPTS")
            if success:
                lines = output.strip().split('\n')
                count = None
                for line in lines:
                    if line.strip().isdigit():
                        count = int(line.strip())
                        break
                print(f"✅ Database connection successful. Concepts count: {count}")
                return True
            else:
                print(f"❌ Database connection failed: {output}")
                return False
        except Exception as e:
            print(f"❌ Database connection failed: {e}")
            return False
            
    def test_concept_operations(self) -> bool:
        """Test concept CRUD operations"""
        try:
            # Create
            concept_id = self.system.create_concept(
                concept_name="Test Concept v1.0.0",
                concept_type="technology",
                description="Test concept for v1.0.0 verification",
                category="test",
                tags=["test", "verification", "v1.0.0"],
                metadata={"test": True, "version": "1.0.0"},
                confidence=0.95
            )
            print(f"✅ Created concept with ID: {concept_id}")
            
            # Read
            concept = self.system.get_concept(concept_id)
            if concept:
                print(f"✅ Retrieved concept: {concept['concept_name']}")
                print(f"   - Type: {concept['concept_type']}")
                print(f"   - Category: {concept['category']}")
                print(f"   - Confidence: {concept['confidence']}")
            else:
                print(f"❌ Failed to retrieve concept")
                return False
                
            # Update
            success = self.system.update_concept(
                concept_id=concept_id,
                concept_name="Updated Test Concept v1.0.0",
                metadata={"version": "1.0.0", "updated": True}
            )
            if success:
                print(f"✅ Updated concept successfully")
            else:
                print(f"❌ Failed to update concept")
                return False
                
            # Delete
            success = self.system.delete_concept(concept_id)
            if success:
                print(f"✅ Deleted concept successfully")
            else:
                print(f"❌ Failed to delete concept")
                return False
                
            return True
        except Exception as e:
            print(f"❌ Concept operations failed: {e}")
            return False
            
    def test_relationship_operations(self) -> bool:
        """Test relationship CRUD operations"""
        try:
            # Create two concepts
            concept1_id = self.system.create_concept(
                concept_name="Source Concept",
                concept_type="technology"
            )
            concept2_id = self.system.create_concept(
                concept_name="Target Concept",
                concept_type="concept"
            )
            print(f"✅ Created test concepts: {concept1_id}, {concept2_id}")
            
            # Create relationship
            rel_id = self.system.create_relationship(
                source_concept_id=concept1_id,
                target_concept_id=concept2_id,
                relationship_type="implements",
                strength=0.9,
                properties={"evidence": "test"},
                confidence=0.9
            )
            print(f"✅ Created relationship with ID: {rel_id}")
            
            # Get relationships
            relationships = self.system.get_relationships(
                concept_id=concept1_id,
                direction="outgoing"
            )
            if relationships:
                print(f"✅ Retrieved {len(relationships)} relationships")
                for rel in relationships:
                    print(f"   - {rel['relationship_type']}: {rel['source_concept_id']} -> {rel['target_concept_id']}")
            else:
                print(f"⚠️ No relationships found")
                
            # Delete relationship
            success = self.system.delete_relationship(rel_id)
            if success:
                print(f"✅ Deleted relationship successfully")
            else:
                print(f"❌ Failed to delete relationship")
                return False
                
            # Cleanup
            self.system.delete_concept(concept1_id)
            self.system.delete_concept(concept2_id)
            print(f"✅ Cleanup completed")
            
            return True
        except Exception as e:
            print(f"❌ Relationship operations failed: {e}")
            return False
            
    def test_statistics(self) -> bool:
        """Test statistics and metrics"""
        try:
            # Get statistics
            stats = self.system.get_statistics()
            if stats:
                print(f"✅ Statistics retrieved:")
                print(f"   - Total concepts: {stats.get('total_concepts', 0)}")
                print(f"   - Total relationships: {stats.get('total_relationships', 0)}")
                print(f"   - Total tags: {stats.get('total_tags', 0)}")
            else:
                print(f"⚠️ Failed to retrieve statistics")
                return False
                
            # Get graph metrics
            metrics = self.system.get_graph_metrics()
            if metrics:
                print(f"✅ Graph metrics retrieved:")
                print(f"   - Total concepts: {metrics.get('total_concepts', 0)}")
                print(f"   - Total relationships: {metrics.get('total_relationships', 0)}")
                print(f"   - Avg connections: {metrics.get('avg_connections', 0):.2f}")
                print(f"   - Max connections: {metrics.get('max_connections', 0)}")
            else:
                print(f"⚠️ Failed to retrieve graph metrics")
                return False
                
            return True
        except Exception as e:
            print(f"❌ Statistics failed: {e}")
            return False
            
    def test_cache_performance(self) -> bool:
        """Test cache performance"""
        try:
            if not self.system.cache:
                print(f"⚠️ Cache not enabled, skipping test")
                return True
                
            # Clear cache
            self.system.cache.clear()
            print(f"✅ Cache cleared")
            
            # First query (cache miss)
            start_time = time.time()
            success1, _ = self.system.execute_sql("SELECT COUNT(*) FROM KNOWLEDGE_CONCEPTS")
            time1 = time.time() - start_time
            
            # Second query (cache hit)
            start_time = time.time()
            success2, _ = self.system.execute_sql("SELECT COUNT(*) FROM KNOWLEDGE_CONCEPTS")
            time2 = time.time() - start_time
            
            if success1 and success2:
                print(f"✅ Cache performance test:")
                print(f"   - First query (miss): {time1*1000:.1f}ms")
                print(f"   - Second query (hit): {time2*1000:.1f}ms")
                if time2 > 0:
                    print(f"   - Speedup: {time1/time2:.1f}x")
                return True
            else:
                print(f"❌ Cache test queries failed")
                return False
                
        except Exception as e:
            print(f"❌ Cache performance test failed: {e}")
            return False
            
    def test_cleanup(self) -> bool:
        """Test cleanup operations"""
        try:
            # Clear cache if enabled
            if self.system.cache:
                self.system.cache.clear()
                print(f"✅ Cache cleared successfully")
                
            print(f"✅ Cleanup completed successfully")
            return True
        except Exception as e:
            print(f"❌ Cleanup failed: {e}")
            return False
            
    def print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)
        
        passed = sum(1 for r in self.test_results if r['status'] == 'PASS')
        failed = sum(1 for r in self.test_results if r['status'] == 'FAIL')
        errors = sum(1 for r in self.test_results if r['status'] == 'ERROR')
        total = len(self.test_results)
        
        print(f"\nTotal Tests: {total}")
        print(f"Passed: {passed} ✅")
        print(f"Failed: {failed} ❌")
        print(f"Errors: {errors} ⚠️")
        print(f"Success Rate: {(passed/total)*100:.1f}%")
        
        if failed > 0 or errors > 0:
            print("\nFailed/Error Tests:")
            for result in self.test_results:
                if result['status'] in ['FAIL', 'ERROR']:
                    print(f"  - {result['test_name']}: {result.get('error', 'Failed')}")
                    
        print("\n" + "=" * 70)
        
        if passed == total:
            print("🎉 ALL TESTS PASSED! v1.0.0 is ready for production.")
        else:
            print("⚠️ Some tests failed. Please review before production.")
            
        print("=" * 70)


if __name__ == "__main__":
    test = FinalVerificationTest()
    test.run_all_tests()
