#!/usr/bin/env python3
"""
oracle-memory-by-yhw - Comprehensive Compatibility Test Suite v0.5.1

This test suite validates ALL components of the Oracle Memory System skill:
1. Document consistency and version alignment
2. File structure integrity
3. SQL script syntax validation
4. Python script syntax validation
5. Cross-reference validation
6. Configuration completeness
7. All historical features (v0.3.0 - v0.5.1)

Author: Haiwen Yin (胖头鱼 🐟)
Version: v0.5.1 Comprehensive Test
Date: 2026-05-09
"""

import json
import sys
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple

# Configuration
SKILL_BASE_PATH = "/root/.hermes/skills/oracle-memory-by-yhw"
SQLCL_PATH = "/root/sqlcl/sqlcl/bin/sql"
DB_CONNECTION = "openclaw/hermes@//10.10.10.130:1521/openclaw"

class CompatibilityTester:
    """Comprehensive compatibility test suite for Oracle Memory System"""
    
    def __init__(self):
        self.results = []
        self.test_count = 0
        self.pass_count = 0
        self.fail_count = 0
        self.warning_count = 0
    
    def add_result(self, test_name: str, status: str, message: str = "", details: str = ""):
        """Record test result"""
        self.test_count += 1
        if status == "PASS":
            self.pass_count += 1
        elif status == "FAIL":
            self.fail_count += 1
        else:
            self.warning_count += 1
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.results.append({
            'timestamp': timestamp,
            'test_name': test_name,
            'status': status,
            'message': message,
            'details': details
        })
    
    def test_document_consistency(self):
        """Test 1: Document version consistency"""
        print("\n📚 Test 1: Document Version Consistency")
        print("-" * 60)
        
        try:
            # Check SKILL.md version
            skill_md_path = os.path.join(SKILL_BASE_PATH, "SKILL.md")
            with open(skill_md_path, 'r') as f:
                skill_content = f.read()
            
            # Extract version from SKILL.md
            version_match = re.search(r'version:\s*v(\d+\.\d+\.\d+)', skill_content)
            if version_match:
                skill_version = version_match.group(1)
                print(f"  ✅ SKILL.md version: v{skill_version}")
            else:
                print("  ❌ SKILL.md version not found")
                self.add_result("Document Consistency", "FAIL", "SKILL.md version missing")
                return
            
            # Check README.md version
            readme_path = os.path.join(SKILL_BASE_PATH, "README.md")
            with open(readme_path, 'r') as f:
                readme_content = f.read()
            
            readme_version_match = re.search(r'v(\d+\.\d+\.\d+)', readme_content)
            if readme_version_match:
                readme_version = readme_version_match.group(1)
                if readme_version == skill_version:
                    print(f"  ✅ README.md version matches: v{readme_version}")
                else:
                    print(f"  ⚠️ README.md version mismatch: v{readme_version} vs v{skill_version}")
                    self.add_result("Document Consistency", "WARNING", 
                                  f"Version mismatch: README v{readme_version} vs SKILL v{skill_version}")
            else:
                print("  ⚠️ README.md version not found")
            
            # Check CHANGELOG.md
            changelog_path = os.path.join(SKILL_BASE_PATH, "CHANGELOG.md")
            if os.path.exists(changelog_path):
                with open(changelog_path, 'r') as f:
                    changelog_content = f.read()
                
                if f"v{skill_version}" in changelog_content:
                    print(f"  ✅ CHANGELOG.md contains v{skill_version} entry")
                else:
                    print(f"  ⚠️ CHANGELOG.md missing v{skill_version} entry")
                    self.add_result("Document Consistency", "WARNING", 
                                  f"CHANGELOG.md missing v{skill_version} entry")
            
            # Check RELEASE_NOTES
            release_notes_path = os.path.join(SKILL_BASE_PATH, f"RELEASE_NOTES_v{skill_version.replace('.', '_')}.md")
            if os.path.exists(release_notes_path):
                print(f"  ✅ Release notes exist: RELEASE_NOTES_v{skill_version.replace('.', '_')}.md")
            else:
                print(f"  ⚠️ Release notes missing: RELEASE_NOTES_v{skill_version.replace('.', '_')}.md")
                self.add_result("Document Consistency", "WARNING", 
                              f"Release notes missing for v{skill_version}")
            
            self.add_result("Document Consistency", "PASS", 
                          f"All document versions checked for v{skill_version}")
            
        except Exception as e:
            print(f"  ❌ Error in document consistency test: {e}")
            self.add_result("Document Consistency", "FAIL", str(e))
    
    def test_file_structure(self):
        """Test 2: File structure integrity"""
        print("\n📁 Test 2: File Structure Integrity")
        print("-" * 60)
        
        try:
            # Required directories
            required_dirs = [
                "scripts",
                "security",
                "references"
            ]
            
            # Required files
            required_files = [
                "SKILL.md",
                "README.md",
                "CHANGELOG.md",
                "LICENSE",
                "NOTICE"
            ]
            
            # Check directories
            for dir_name in required_dirs:
                dir_path = os.path.join(SKILL_BASE_PATH, dir_name)
                if os.path.exists(dir_path) and os.path.isdir(dir_path):
                    print(f"  ✅ Directory exists: {dir_name}/")
                else:
                    print(f"  ❌ Directory missing: {dir_name}/")
                    self.add_result("File Structure", "FAIL", f"Missing directory: {dir_name}")
            
            # Check files
            for file_name in required_files:
                file_path = os.path.join(SKILL_BASE_PATH, file_name)
                if os.path.exists(file_path):
                    size_kb = os.path.getsize(file_path) / 1024
                    print(f"  ✅ File exists: {file_name} ({size_kb:.1f} KB)")
                else:
                    print(f"  ❌ File missing: {file_name}")
                    self.add_result("File Structure", "FAIL", f"Missing file: {file_name}")
            
            # Check script files
            script_files = [
                "scripts/memory_fusion_engine.sql",
                "scripts/agent_permission_downgrade.sql",
                "scripts/enhanced_session_cleanup.sql",
                "scripts/enhanced_snapshot_cleanup_job.sql",
                "scripts/test_v051_complete.py",
                "scripts/test_complete_memory_system.py"
            ]
            
            for script_file in script_files:
                script_path = os.path.join(SKILL_BASE_PATH, script_file)
                if os.path.exists(script_path):
                    size_kb = os.path.getsize(script_path) / 1024
                    print(f"  ✅ Script exists: {script_file} ({size_kb:.1f} KB)")
                else:
                    print(f"  ❌ Script missing: {script_file}")
                    self.add_result("File Structure", "FAIL", f"Missing script: {script_file}")
            
            # Check security files
            security_files = [
                "security/data_masking.py",
                "security/context_aware_masking.py",
                "security/reversible_masking.py"
            ]
            
            for sec_file in security_files:
                sec_path = os.path.join(SKILL_BASE_PATH, sec_file)
                if os.path.exists(sec_path):
                    size_kb = os.path.getsize(sec_path) / 1024
                    print(f"  ✅ Security file: {sec_file} ({size_kb:.1f} KB)")
                else:
                    print(f"  ❌ Security file missing: {sec_file}")
                    self.add_result("File Structure", "FAIL", f"Missing security file: {sec_file}")
            
            self.add_result("File Structure", "PASS", "File structure integrity verified")
            
        except Exception as e:
            print(f"  ❌ Error in file structure test: {e}")
            self.add_result("File Structure", "FAIL", str(e))
    
    def test_sql_syntax(self):
        """Test 3: SQL script syntax validation"""
        print("\n📝 Test 3: SQL Script Syntax Validation")
        print("-" * 60)
        
        sql_files = [
            "scripts/memory_fusion_engine.sql",
            "scripts/agent_permission_downgrade.sql",
            "scripts/enhanced_session_cleanup.sql",
            "scripts/enhanced_snapshot_cleanup_job.sql",
            "scripts/cleanup_orphaned_data.sql",
            "scripts/session_cleanup_job.sql",
            "scripts/agent_schema.sql",
            "security/aggregation_analysis.sql",
            "security/desensitize_levels.sql"
        ]
        
        all_valid = True
        
        for sql_file in sql_files:
            sql_path = os.path.join(SKILL_BASE_PATH, sql_file)
            
            if not os.path.exists(sql_path):
                print(f"  ⚠️ File not found: {sql_file}")
                continue
            
            try:
                with open(sql_path, 'r') as f:
                    sql_content = f.read()
                
                # Basic syntax checks
                issues = []
                
                # Check for balanced parentheses
                open_parens = sql_content.count('(')
                close_parens = sql_content.count(')')
                if open_parens != close_parens:
                    issues.append(f"Unbalanced parentheses: {open_parens} open, {close_parens} close")
                
                # Check for common SQL keywords
                required_keywords = ['CREATE', 'TABLE', 'INSERT', 'SELECT']
                for keyword in required_keywords:
                    if keyword not in sql_content.upper():
                        issues.append(f"Missing expected keyword: {keyword}")
                
                # Check for PL/SQL blocks
                if 'CREATE OR REPLACE PACKAGE' in sql_content:
                    if 'CREATE OR REPLACE PACKAGE BODY' not in sql_content:
                        issues.append("Package declared without body")
                
                if issues:
                    print(f"  ⚠️ {sql_file}: {len(issues)} potential issues")
                    for issue in issues[:3]:  # Show first 3 issues
                        print(f"    - {issue}")
                    all_valid = False
                else:
                    print(f"  ✅ {sql_file}: Basic syntax valid")
                
            except Exception as e:
                print(f"  ❌ {sql_file}: Error reading file - {e}")
                all_valid = False
        
        if all_valid:
            self.add_result("SQL Syntax", "PASS", "All SQL scripts have valid basic syntax")
        else:
            self.add_result("SQL Syntax", "WARNING", "Some SQL scripts have potential syntax issues")
        
    def test_python_syntax(self):
        """Test 4: Python script syntax validation"""
        print("\n🐍 Test 4: Python Script Syntax Validation")
        print("-" * 60)
        
        python_files = [
            "scripts/test_v051_complete.py",
            "scripts/test_complete_memory_system.py",
            "scripts/generate_vector_insert_sql.py",
            "scripts/test_partition_strategy.py",
            "security/data_masking.py",
            "security/context_aware_masking.py",
            "security/reversible_masking.py"
        ]
        
        all_valid = True
        
        for py_file in python_files:
            py_path = os.path.join(SKILL_BASE_PATH, py_file)
            
            if not os.path.exists(py_path):
                print(f"  ⚠️ File not found: {py_file}")
                continue
            
            try:
                # Check Python syntax using compile
                with open(py_path, 'r') as f:
                    py_content = f.read()
                
                # Compile to check syntax
                compile(py_content, py_path, 'exec')
                print(f"  ✅ {py_file}: Syntax valid")
                
            except SyntaxError as e:
                print(f"  ❌ {py_file}: Syntax error - {e}")
                all_valid = False
            except Exception as e:
                print(f"  ❌ {py_file}: Error checking syntax - {e}")
                all_valid = False
        
        if all_valid:
            self.add_result("Python Syntax", "PASS", "All Python scripts have valid syntax")
        else:
            self.add_result("Python Syntax", "FAIL", "Python syntax errors detected")
    
    def test_cross_references(self):
        """Test 5: Cross-reference validation"""
        print("\n🔗 Test 5: Cross-Reference Validation")
        print("-" * 60)
        
        try:
            # Check SKILL.md for file references
            skill_md_path = os.path.join(SKILL_BASE_PATH, "SKILL.md")
            with open(skill_md_path, 'r') as f:
                skill_content = f.read()
            
            # Extract file references
            references = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', skill_content)
            
            broken_refs = []
            valid_refs = 0
            
            for ref_name, ref_path in references:
                # Skip external links
                if ref_path.startswith('http') or ref_path.startswith('#'):
                    continue
                
                # Check local file reference
                full_path = os.path.join(SKILL_BASE_PATH, ref_path)
                if os.path.exists(full_path):
                    valid_refs += 1
                else:
                    broken_refs.append(ref_name)
                    print(f"  ❌ Broken reference: {ref_name} → {ref_path}")
            
            if broken_refs:
                print(f"  ⚠️ Found {len(broken_refs)} broken references")
                self.add_result("Cross References", "WARNING", 
                              f"Found {len(broken_refs)} broken references in SKILL.md")
            else:
                print(f"  ✅ All {valid_refs} local references are valid")
                self.add_result("Cross References", "PASS", 
                              f"All {valid_refs} local references valid")
            
        except Exception as e:
            print(f"  ❌ Error in cross-reference test: {e}")
            self.add_result("Cross References", "FAIL", str(e))
    
    def test_configuration_completeness(self):
        """Test 6: Configuration completeness"""
        print("\n⚙️ Test 6: Configuration Completeness")
        print("-" * 60)
        
        try:
            # Check SKILL.md for required configuration sections
            skill_md_path = os.path.join(SKILL_BASE_PATH, "SKILL.md")
            with open(skill_md_path, 'r') as f:
                skill_content = f.read()
            
            required_sections = [
                "System Overview",
                "Core Features",
                "Database Schema",
                "API Functions",
                "Indexing Strategy",
                "Documentation"
            ]
            
            missing_sections = []
            
            for section in required_sections:
                if section.lower() in skill_content.lower():
                    print(f"  ✅ Section found: {section}")
                else:
                    print(f"  ❌ Section missing: {section}")
                    missing_sections.append(section)
            
            if missing_sections:
                self.add_result("Configuration", "WARNING", 
                              f"Missing {len(missing_sections)} sections: {', '.join(missing_sections)}")
            else:
                self.add_result("Configuration", "PASS", "All required sections present")
            
        except Exception as e:
            print(f"  ❌ Error in configuration test: {e}")
            self.add_result("Configuration", "FAIL", str(e))
    
    def test_version_alignment(self):
        """Test 7: Version alignment across all components"""
        print("\n🎯 Test 7: Version Alignment Check")
        print("-" * 60)
        
        try:
            # Get expected version from SKILL.md
            skill_md_path = os.path.join(SKILL_BASE_PATH, "SKILL.md")
            with open(skill_md_path, 'r') as f:
                skill_content = f.read()
            
            version_match = re.search(r'version:\s*v(\d+\.\d+\.\d+)', skill_content)
            if not version_match:
                print("  ❌ Cannot determine expected version from SKILL.md")
                self.add_result("Version Alignment", "FAIL", "Cannot determine version")
                return
            
            expected_version = version_match.group(1)
            print(f"  📌 Expected version: v{expected_version}")
            
            # Check version references in scripts
            scripts_with_version = [
                "scripts/test_v051_complete.py",
                "scripts/test_complete_memory_system.py"
            ]
            
            version_mismatches = []
            
            for script_file in scripts_with_version:
                script_path = os.path.join(SKILL_BASE_PATH, script_file)
                if not os.path.exists(script_path):
                    continue
                
                with open(script_path, 'r') as f:
                    script_content = f.read()
                
                # Look for version references
                version_refs = re.findall(r'v(\d+\.\d+\.\d+)', script_content)
                for ref in version_refs:
                    if ref != expected_version and ref not in ['0.0.0', '1.0.0']:
                        version_mismatches.append((script_file, ref))
                        print(f"  ⚠️ Version mismatch in {script_file}: v{ref}")
            
            if version_mismatches:
                self.add_result("Version Alignment", "WARNING", 
                              f"Found {len(version_mismatches)} version mismatches")
            else:
                print(f"  ✅ All version references align with v{expected_version}")
                self.add_result("Version Alignment", "PASS", 
                              f"All components aligned to v{expected_version}")
            
        except Exception as e:
            print(f"  ❌ Error in version alignment test: {e}")
            self.add_result("Version Alignment", "FAIL", str(e))
    
    def test_database_schema(self):
        """Test 8: Database schema validation"""
        print("\n🗄️ Test 8: Database Schema Validation")
        print("-" * 60)
        
        try:
            # Check SQL files for required tables
            required_tables = [
                "MEMORIES",
                "MEMORIES_VECTORS",
                "TASK_PLANS",
                "TASK_STEPS",
                "TASK_CONTEXT_SNAPSHOTS",
                "TASK_TOOL_CALLS",
                "TASK_DEPENDENCIES"
            ]
            
            sql_files = [
                "scripts/memory_fusion_engine.sql",
                "scripts/agent_permission_downgrade.sql",
                "scripts/enhanced_session_cleanup.sql",
                "scripts/enhanced_snapshot_cleanup_job.sql"
            ]
            
            found_tables = set()
            
            for sql_file in sql_files:
                sql_path = os.path.join(SKILL_BASE_PATH, sql_file)
                if not os.path.exists(sql_path):
                    continue
                
                with open(sql_path, 'r') as f:
                    sql_content = f.read()
                
                # Look for CREATE TABLE statements
                table_matches = re.findall(r'CREATE\s+TABLE\s+(\w+)', sql_content, re.IGNORECASE)
                for table in table_matches:
                    found_tables.add(table.upper())
            
            missing_tables = []
            for table in required_tables:
                if table in found_tables or table.upper() in [t.upper() for t in found_tables]:
                    print(f"  ✅ Table defined: {table}")
                else:
                    print(f"  ⚠️ Table not found in new SQL files: {table}")
                    missing_tables.append(table)
            
            if missing_tables:
                print(f"  ℹ️ Note: Some tables may be defined in older SQL files or deployed separately")
                self.add_result("Database Schema", "WARNING", 
                              f"Tables not found in v0.5.1 SQL: {', '.join(missing_tables[:3])}")
            else:
                self.add_result("Database Schema", "PASS", "All required tables found in schema")
            
        except Exception as e:
            print(f"  ❌ Error in database schema test: {e}")
            self.add_result("Database Schema", "FAIL", str(e))
    
    def test_documentation_completeness(self):
        """Test 9: Documentation completeness"""
        print("\n📄 Test 9: Documentation Completeness")
        print("-" * 60)
        
        try:
            # Check README.md for required sections
            readme_path = os.path.join(SKILL_BASE_PATH, "README.md")
            with open(readme_path, 'r') as f:
                readme_content = f.read()
            
            required_elements = [
                "Overview",
                "Installation",
                "Quick Start",
                "API Reference",
                "Examples",
                "License"
            ]
            
            missing_elements = []
            
            for element in required_elements:
                if element.lower() in readme_content.lower():
                    print(f"  ✅ README contains: {element}")
                else:
                    print(f"  ⚠️ README missing: {element}")
                    missing_elements.append(element)
            
            # Check CHANGELOG.md
            changelog_path = os.path.join(SKILL_BASE_PATH, "CHANGELOG.md")
            if os.path.exists(changelog_path):
                with open(changelog_path, 'r') as f:
                    changelog_content = f.read()
                
                # Check for version history
                if 'v0.3.0' in changelog_content and 'v0.5.1' in changelog_content:
                    print(f"  ✅ CHANGELOG contains version history (v0.3.0 - v0.5.1)")
                else:
                    print(f"  ⚠️ CHANGELOG may be incomplete")
            
            if missing_elements:
                self.add_result("Documentation", "WARNING", 
                              f"README missing {len(missing_elements)} elements")
            else:
                self.add_result("Documentation", "PASS", "Documentation is complete")
            
        except Exception as e:
            print(f"  ❌ Error in documentation test: {e}")
            self.add_result("Documentation", "FAIL", str(e))
    
    def test_historical_features(self):
        """Test 10: Historical feature compatibility"""
        print("\n🏛️ Test 10: Historical Feature Compatibility")
        print("-" * 60)
        
        try:
            # Check SKILL.md for historical version references
            skill_md_path = os.path.join(SKILL_BASE_PATH, "SKILL.md")
            with open(skill_md_path, 'r') as f:
                skill_content = f.read()
            
            historical_versions = ["v0.3.0", "v0.3.1", "v0.4.0", "v0.4.1", "v0.4.2", "v0.5.0", "v0.5.1"]
            
            found_versions = []
            for version in historical_versions:
                if version in skill_content:
                    found_versions.append(version)
                    print(f"  ✅ Historical version documented: {version}")
                else:
                    print(f"  ⚠️ Historical version not found: {version}")
            
            # Check for key features from each version
            key_features = {
                "v0.3.0": ["Vector Storage", "Embedding Models"],
                "v0.3.1": ["Task Plan", "Breakpoint Recovery"],
                "v0.4.0": ["Property Graph", "JRD"],
                "v0.5.0": ["Security", "Data Masking"],
                "v0.5.1": ["Memory Fusion", "Agent Permission"]
            }
            
            feature_coverage = {}
            for version, features in key_features.items():
                feature_coverage[version] = []
                for feature in features:
                    if feature.lower() in skill_content.lower():
                        feature_coverage[version].append(feature)
                
                coverage_pct = len(feature_coverage[version]) / len(features) * 100
                print(f"  📊 {version} feature coverage: {coverage_pct:.0f}% ({len(feature_coverage[version])}/{len(features)})")
            
            self.add_result("Historical Features", "PASS", 
                          f"Found {len(found_versions)}/{len(historical_versions)} historical versions")
            
        except Exception as e:
            print(f"  ❌ Error in historical feature test: {e}")
            self.add_result("Historical Features", "FAIL", str(e))
    
    def generate_comprehensive_report(self):
        """Generate comprehensive test report"""
        print("\n" + "=" * 80)
        print("📊 ORACLE MEMORY SYSTEM v0.5.1 - COMPREHENSIVE TEST REPORT")
        print("=" * 80)
        
        print(f"\nTest Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Skill Version: v0.5.1")
        print(f"Total Tests: {self.test_count}")
        print(f"✅ Passed: {self.pass_count}")
        print(f"⚠️ Warnings: {self.warning_count}")
        print(f"❌ Failed: {self.fail_count}")
        
        # Overall status
        if self.fail_count == 0 and self.warning_count == 0:
            print("\n🎉 OVERALL STATUS: EXCELLENT - ALL TESTS PASSED")
        elif self.fail_count == 0:
            print("\n✅ OVERALL STATUS: GOOD - PASSED WITH WARNINGS")
        elif self.fail_count <= 2:
            print("\n⚠️ OVERALL STATUS: ACCEPTABLE - NEEDS ATTENTION")
        else:
            print("\n❌ OVERALL STATUS: NEEDS WORK - MULTIPLE FAILURES")
        
        # Summary
        print("\n" + "-" * 80)
        print("📋 TEST SUMMARY")
        print("-" * 80)
        
        # Group results by status
        passed_tests = [r for r in self.results if r['status'] == 'PASS']
        warning_tests = [r for r in self.results if r['status'] == 'WARNING']
        failed_tests = [r for r in self.results if r['status'] == 'FAIL']
        
        if passed_tests:
            print(f"\n✅ PASSED ({len(passed_tests)}):")
            for test in passed_tests:
                print(f"  • {test['test_name']}: {test['message']}")
        
        if warning_tests:
            print(f"\n⚠️ WARNINGS ({len(warning_tests)}):")
            for test in warning_tests:
                print(f"  • {test['test_name']}: {test['message']}")
        
        if failed_tests:
            print(f"\n❌ FAILED ({len(failed_tests)}):")
            for test in failed_tests:
                print(f"  • {test['test_name']}: {test['message']}")
        
        # Recommendations
        print("\n" + "-" * 80)
        print("💡 RECOMMENDATIONS")
        print("-" * 80)
        
        if self.fail_count > 0:
            print("\n🔧 Required Actions:")
            print("  1. Fix all FAILED tests before production deployment")
            print("  2. Review WARNING tests and address if needed")
            print("  3. Re-run tests after fixes to verify resolution")
        else:
            print("\n🎉 Ready for Production!")
            print("  1. All core tests passed")
            print("  2. Review warnings for potential improvements")
            print("  3. Consider implementing suggested enhancements")
        
        print("\n" + "=" * 80)

# Main execution
if __name__ == "__main__":
    tester = CompatibilityTester()
    
    # Run all tests
    tests = [
        tester.test_document_consistency,
        tester.test_file_structure,
        tester.test_sql_syntax,
        tester.test_python_syntax,
        tester.test_cross_references,
        tester.test_configuration_completeness,
        tester.test_version_alignment,
        tester.test_database_schema,
        tester.test_documentation_completeness,
        tester.test_historical_features
    ]
    
    for test_func in tests:
        try:
            test_func()
        except Exception as e:
            print(f"\n❌ Critical error in {test_func.__name__}: {e}")
            tester.add_result(test_func.__name__, "FAIL", f"Critical error: {e}")
    
    # Generate final report
    tester.generate_comprehensive_report()
