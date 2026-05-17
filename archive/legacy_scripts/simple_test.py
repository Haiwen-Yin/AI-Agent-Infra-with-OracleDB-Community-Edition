"""
Simple test for Oracle Memory System
"""
import subprocess
import json
import time

SQLCL_PATH = "/root/sqlcl/bin/sql"
DB_CONNECTION = "openclaw/hermes@//10.10.10.130:1521/openclaw"

def execute_sql(sql):
    """Execute SQL via SQLcl"""
    cmd = f'echo "{sql}" | {SQLCL_PATH} {DB_CONNECTION}'
    try:
        process = subprocess.run(
            ['bash', '-c', cmd],
            capture_output=True,
            text=True,
            timeout=30
        )
        return (process.returncode == 0, process.stdout)
    except Exception as e:
        return (False, str(e))

def test_connection():
    """Test database connection"""
    print("1. Testing database connection...")
    success, output = execute_sql("SELECT COUNT(*) FROM memories")
    if success:
        lines = output.strip().split('\n')
        for line in lines:
            if line.strip().isdigit():
                print(f"   ✅ Connection OK. Memories count: {line.strip()}")
                return True
    print(f"   ❌ Connection failed")
    return False

def test_get_statistics():
    """Test get_statistics"""
    print("\n2. Testing get_statistics...")
    sql = """
        SELECT 
            (SELECT COUNT(*) FROM memories WHERE status = 'active') AS total_memories,
            (SELECT COUNT(*) FROM knowledge_concepts WHERE status = 'active') AS total_concepts,
            (SELECT COUNT(*) FROM knowledge_relationships WHERE status = 'active') AS total_relationships
        FROM DUAL
    """
    success, output = execute_sql(sql)
    if success:
        print(f"   ✅ Statistics query OK")
        # Parse output
        lines = output.strip().split('\n')
        for i, line in enumerate(lines):
            if 'total_memories' in line.lower():
                if i + 1 < len(lines):
                    values = lines[i + 1].split('|')
                    if len(values) >= 3:
                        try:
                            stats = {
                                'total_memories': int(values[0].strip()),
                                'total_concepts': int(values[1].strip()),
                                'total_relationships': int(values[2].strip())
                            }
                            print(f"   Stats: {stats}")
                            return True
                        except ValueError:
                            pass
    print(f"   ❌ Statistics query failed")
    return False

def test_create_concept():
    """Test create_concept"""
    print("\n3. Testing create_concept...")
    sql = """
        INSERT INTO knowledge_concepts (name, concept_type, description, properties, tags)
        VALUES ('Test Concept v1.0', 'technology', 'Test description', '{"version":"1.0"}', '["test"]')
    """
    success, output = execute_sql(sql)
    if success:
        # Get the ID
        id_sql = "SELECT concept_id FROM knowledge_concepts WHERE name = 'Test Concept v1.0'"
        success, id_output = execute_sql(id_sql)
        if success:
            lines = id_output.strip().split('\n')
            for line in lines:
                if line.strip().isdigit():
                    concept_id = int(line.strip())
                    print(f"   ✅ Created concept with ID: {concept_id}")
                    return concept_id
    print(f"   ❌ Create concept failed")
    return None

def test_get_concept(concept_id):
    """Test get_concept"""
    print("\n4. Testing get_concept...")
    sql = f"""
        SELECT concept_id, name, concept_type, description
        FROM knowledge_concepts
        WHERE concept_id = {concept_id}
    """
    success, output = execute_sql(sql)
    if success:
        lines = output.strip().split('\n')
        for i, line in enumerate(lines):
            if 'concept_id' in line.lower() and 'name' in line.lower():
                if i + 1 < len(lines):
                    values = lines[i + 1].split('|')
                    if len(values) >= 2:
                        print(f"   ✅ Retrieved concept: {values[1].strip()}")
                        return True
    print(f"   ❌ Get concept failed")
    return False

def test_delete_concept(concept_id):
    """Test delete_concept"""
    print("\n5. Testing delete_concept...")
    sql = f"DELETE FROM knowledge_concepts WHERE concept_id = {concept_id}"
    success, output = execute_sql(sql)
    if success:
        print(f"   ✅ Deleted concept")
        return True
    print(f"   ❌ Delete concept failed")
    return False

def test_create_relationship():
    """Test create_relationship"""
    print("\n6. Testing create_relationship...")
    
    # Create two concepts
    sql1 = "INSERT INTO knowledge_concepts (name, concept_type) VALUES ('Source', 'tech')"
    execute_sql(sql1)
    
    sql2 = "INSERT INTO knowledge_concepts (name, concept_type) VALUES ('Target', 'tech')"
    execute_sql(sql2)
    
    # Get IDs
    id1_sql = "SELECT concept_id FROM knowledge_concepts WHERE name = 'Source'"
    success, id1_output = execute_sql(id1_sql)
    id1 = None
    for line in id1_output.strip().split('\n'):
        if line.strip().isdigit():
            id1 = int(line.strip())
            break
            
    id2_sql = "SELECT concept_id FROM knowledge_concepts WHERE name = 'Target'"
    success, id2_output = execute_sql(id2_sql)
    id2 = None
    for line in id2_output.strip().split('\n'):
        if line.strip().isdigit():
            id2 = int(line.strip())
            break
            
    if id1 and id2:
        # Create relationship
        rel_sql = f"""
            INSERT INTO knowledge_relationships 
            (source_concept_id, target_concept_id, relationship_type, strength)
            VALUES ({id1}, {id2}, 'implements', 0.9)
        """
        success, _ = execute_sql(rel_sql)
        if success:
            print(f"   ✅ Created relationship")
            # Cleanup
            execute_sql(f"DELETE FROM knowledge_relationships WHERE source_concept_id = {id1}")
            execute_sql(f"DELETE FROM knowledge_concepts WHERE concept_id IN ({id1}, {id2})")
            return True
            
    print(f"   ❌ Create relationship failed")
    return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("Oracle AI Database Memory System v1.0.0 - Simple Test")
    print("=" * 60)
    
    results = []
    
    # Run tests
    results.append(("Connection", test_connection()))
    results.append(("Statistics", test_get_statistics()))
    
    concept_id = test_create_concept()
    results.append(("Create Concept", concept_id is not None))
    
    if concept_id:
        results.append(("Get Concept", test_get_concept(concept_id)))
        results.append(("Delete Concept", test_delete_concept(concept_id)))
        
    results.append(("Create Relationship", test_create_relationship()))
    
    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
        
    print(f"\nTotal: {total}, Passed: {passed}, Success Rate: {passed/total*100:.1f}%")
    print("=" * 60)
    
    if passed == total:
        print("🎉 ALL TESTS PASSED!")
    else:
        print("⚠️ Some tests failed")

if __name__ == "__main__":
    main()
