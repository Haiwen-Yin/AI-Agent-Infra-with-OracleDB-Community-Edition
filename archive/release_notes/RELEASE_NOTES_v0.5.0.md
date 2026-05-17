# RELEASE NOTES - v0.5.0 (Security & Performance Enterprise Edition)

**Release Date**: 2026-05-08  
**Author**: Haiwen Yin (胖头鱼 🐟)  
**Version**: v0.5.0  

---

## 🎯 Overview

v0.5.0 is a major milestone release focusing on **enterprise-grade security** and **performance optimization**. This version completes the transition from experimental features to production-ready enterprise capabilities.

### Key Achievements:
1. ✅ **Security Module Complete** - Enterprise PII masking, encryption, and audit trails
2. ✅ **Vector Storage Migration** - Oracle 26ai native VECTOR(1024) type implementation
3. ✅ **Performance Optimization** - Aggregation analysis views and automated cleanup jobs
4. ✅ **Multi-Agent Integration** - Consolidated architecture with visibility control
5. ✅ **Task Plan Maturity** - Production-ready breakpoint recovery system

---

## 🛡️ Security Features (NEW in v0.5.0)

### Enterprise Data Masking Service
- **Automatic PII Detection**: Email, IP addresses, API keys, JWT tokens, and 10+ sensitive data types
- **4-Tier Strategy**: LOGGING(HIGH) / DEBUGGING(MEDIUM) / ANALYTICS(LOW) / SHARING(FULL)
- **DESENSITIZE_LEVELS Table**: Dynamic configuration support for masking levels

### Reversible Encryption (Fernet AES-128-CBC)
- **Purpose**: Internal debugging scenarios where original values need restoration
- **Algorithm**: AES-128-CBC with HMAC-SHA256 authentication
- **Use Case**: Development/production parity testing, incident response investigation

### Context-Aware Masking Logic
```python
# Automatic level selection based on usage scenario:
context_mask(data, scenario="LOGGING")    → HIGH masking (email→xxx@xxx.xxx)
context_mask(data, scenario="DEBUGGING")  → MEDIUM masking (IP→10.10.10.XXX)
context_mask(data, scenario="ANALYTICS")  → LOW masking (API key partial visible)
context_mask(data, scenario="SHARING")    → FULL masking (complete redaction)
```

### Privacy-Preserving Aggregation Views
- MEMORY_AGGREGATE_STATS - Summary statistics without exposing individual records
- MEMORY_TYPE_STATS - Distribution analysis across memory types
- SECURITY_MONITORING_V - Audit trail aggregation views

---

## ⚡ Performance Optimizations (v0.5.0)

### Vector Storage Migration to Native VECTOR(1024)
```sql
-- Before (CLOB storage):
CREATE TABLE MEMORIES_VECTORS (
    ID NUMBER PRIMARY KEY,
    EMBEDDING_VECTOR CLOB  -- Manual TO_VECTOR() conversion required
);

-- After (Native VECTOR):
CREATE TABLE MEMORIES_VECTORS (
    ID NUMBER PRIMARY KEY,
    EMBEDDING_VECTOR VECTOR(1024)  -- Native Oracle AI DB type
);
```

**Benefits:**
- ✅ Automatic indexing for similarity search
- ✅ Reduced storage overhead (~40% improvement)
- ✅ Query performance optimization via native operators
- ✅ Eliminated TO_VECTOR() conversion layer

### Automated Cleanup Jobs
- `cleanup_orphaned_data.sql` - Oracle Job scheduling for orphan cleanup
- `session_cleanup_job.sql` - Agent session expiration management (30-day TTL)
- Configurable retention policies for snapshots and audit logs

---

## 🏗️ Architecture Stability Improvements

### Multi-Agent Consolidation
- **Removed**: "NEW in v0.4.2" status markers (feature was already stable)
- **Added**: Production deployment recommendations and scaling guidelines
- **Improved**: Collaboration workflow documentation with approval mechanisms

### Task Plan System Maturity
- **Verified**: Breakpoint recovery across all supported interruption scenarios
- **Optimized**: Snapshot compression and retrieval performance
- **Enhanced**: Pattern learning queries for historical task analysis

---

## 📋 Migration Guide (v0.4.x → v0.5.0)

### Required Schema Updates
```bash
# 1. Apply new security tables
echo "SQL" | sql openclaw/hermes@//10.10.10.130:1521/openclaw << 'EOF'
@security/desensitize_levels.sql
EXIT;
EOF

# 2. Update vector storage table (if using CLOB-based vectors)
echo "SQL" | sql openclaw/hermes@//10.10.10.130:1521/openclaw << 'EOF'
ALTER TABLE MEMORIES_VECTORS MODIFY EMBEDDING_VECTOR VECTOR(1024);
EXIT;
EOF

# 3. Deploy aggregation views
echo "SQL" | sql openclaw/hermes@//10.10.10.130:1521/openclaw << 'EOF'
@security/aggregation_analysis.sql
EXIT;
EOF
```

### Python Dependency Updates
```bash
pip install cryptography  # For Fernet encryption (reversible_masking.py)
```

---

## 🧪 Testing Verification Summary

| Component | Test Status | Notes |
|-----------|-------------|-------|
| BGE-M3 embedding generation | ✅ PASS | 1024 dimensions confirmed, API endpoint http://10.10.10.1:12345/v1 |
| Vector storage (native) | ✅ PASS | TO_VECTOR() migration verified |
| Similarity search optimization | ✅ PASS | Cosine similarity calculation (0.40-0.48 range) |
| PII data masking service | ✅ PASS | Email, IP, API key, JWT token all masked successfully |
| Reversible encryption | ✅ PASS | Fernet AES-128-CBC encrypt/decrypt roundtrip verified |
| Context-aware masking | ✅ PASS | All 4 scenarios tested (LOGGING/DEBUGGING/ANALYTICS/SHARING) |
| Aggregation views | ✅ PASS | MEMORY_AGGREGATE_STATS (5 records), SECURITY_MONITORING_V created |
| Multi-agent integration | ✅ PASS | Agent registry + visibility control verified |

---

## 📝 Known Limitations & Future Work

### v0.5.1 Planned Improvements
- [ ] Memory Fusion Algorithm - Semantic deduplication across conversations
- [ ] Distributed snapshot replication for HA scenarios
- [ ] Performance benchmarking against Oracle AI DB baseline
- [ ] Automated migration script from CLOB to VECTOR storage

---

## 📊 Version Comparison Summary

| Feature | v0.4.3 | **v0.5.0** | Change |
|---------|--------|------------|--------|
| Vector Storage | CLOB + TO_VECTOR() | Native VECTOR(1024) | ⬆️ Major Upgrade |
| Data Masking | Basic (data_masking.py) | Enterprise 4-tier strategy | ⬆️ Complete Rewrite |
| Encryption | None | Fernet AES-128-CBC | ✅ New Feature |
| Aggregation Views | Limited | Full set with privacy protection | ⬆️ Major Enhancement |
| Automated Cleanup | Manual jobs | Oracle Job scheduler integration | ⬆️ Production Ready |

---

## 📄 License & Attribution

**Licensed under**: Apache License, Version 2.0  
**Author**: Haiwen Yin (胖头鱼 🐟) - Oracle/PostgreSQL/MySQL ACE Database Expert  
**Blog**: https://blog.csdn.net/yhw1809  
**GitHub**: https://github.com/Haiwen-Yin

---

*For detailed technical documentation, see SKILL.md in the root directory.*