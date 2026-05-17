# Oracle Memory System v0.4.2 - Release Notes

**Release Date**: May 7, 2026  
**Version**: v0.4.2 (Directory Consolidation Update)  
**Upgrade Level**: Patch - Internal Cleanup & Naming Standardization  

---

## 🎯 Executive Summary

v0.4.2 focuses on **internal consistency improvements** and **skill directory consolidation**. No functional changes to the Oracle Memory System itself — this release addresses organizational structure and naming standardization.

---

## 🔧 Changes in v0.4.2

### 1. Directory Structure Consolidation

| Change | Details |
|--------|---------|
| **Directory Rename** | `oracle-memory-by-yhw-v0.4.1/` → `oracle-memory-by-yhw/` (version removed from directory name) |
| **SKILL.md Name Field** | Updated frontmatter: `name: oracle-memory-by-yhw` |
| **Skill Snapshot Update** | All references in `.skills_prompt_snapshot.json` updated to new path |

### 2. Independent Sub-skill Removal

Removed redundant standalone sub-skills that duplicated content from the main skill:

| Removed Directory | Reason for Removal |
|-------------------|-------------------|
| `oracle-memory/` (parent directory) | Contained obsolete sub-skills with duplicated documentation |
| ↳ `oracle-26ai-memory-system-deployment-sop` | Deployment SOP now documented in main SKILL.md |
| ↳ `oracle-memory-schema-design` | Schema design already integrated into main skill |
| ↳ `oracle-memory-version-upgrade-sop` | Version upgrade procedures consolidated into v0.4.1+ |
| ↳ `oracle-memory-python-script-dependency-fix` | Content merged into main skill's reference docs |

### 3. Reference Documentation Integration

**Merged into**: `references/script-deployment-troubleshooting.md`

This file consolidates the Python script dependency troubleshooting guide previously available as a standalone sub-skill, covering:
- hermes_tools import error resolution
- Oracle database connection format standards
- Script corruption detection criteria

---

## 📋 Version History Reference

### v0.4.1 (Task Plan Integration Edition) - May 4, 2026
**Major features**: Task Plan Persistence System with breakpoint recovery, historical learning API, automatic snapshot mechanism.

> **Note for v0.4.1 → v0.4.2 migration**: No database or code changes required. Only internal directory structure adjustments.

---

## 📊 Summary Statistics

| Metric | Value |
|--------|-------|
| Directory renames | 1 (`oracle-memory-by-yhw-v0.4.1` → `oracle-memory-by-yhw`) |
| Sub-skills removed | 4 (from independent oracle-memory/ directory) |
| Reference docs added | 1 (script-deployment-troubleshooting.md) |
| SKILL.md updates | 1 (name field in frontmatter) |
| Functional changes | **0** — internal cleanup only |

---

## ✅ Verification Checklist

- [x] Directory renamed correctly (`oracle-memory-by-yhw/`)
- [x] SKILL.md frontmatter updated (`name: oracle-memory-by-yhw`)
- [x].skills_prompt_snapshot.json references updated (verified 0 v0.4.1 remnants)
- [x] RELEASE_NOTES file renamed to match new version
- [x] No functional changes to Oracle Memory System features

---

## 📚 Related Documentation

- [SKILL.md](./SKILL.md) - Complete system documentation
- [README.md](./README.md) - System architecture overview  
- [CHANGELOG.md](./CHANGELOG.md) - Full version history
- [references/script-deployment-troubleshooting.md](./references/script-deployment-troubleshooting.md) - Script deployment guide

---

**Release Manager**: Haiwen Yin (胖头鱼 🐟)  
**Verification Status**: ✅ Internal structure cleanup verified, no functional regression expected
