# Knowledge Graph Visualization Implementation

**Author**: Haiwen Yin (胖头鱼 🐟) | Date: 2026-05-12  
**Skill**: oracle-memory-by-yhw v1.0.0

---

## Overview

Knowledge graph visualization module implemented for oracle-memory-by-yhw skill on 2026-05-12. Provides three complementary approaches to explore and visualize knowledge graphs stored in Oracle AI Database.

---

## Implementation Details

### Scripts Created

1. **knowledge_graph_report.py** (3.1 KB)
   - Text-based report generator
   - No external dependencies
   - Executes via SQLcl
   - Output: `/tmp/knowledge_graph_visualization/knowledge_graph_report_<timestamp>.txt`

2. **export_graph_fixed.py** (5.9 KB) 
   - Multi-format graph exporter
   - Fixed version with correct SQL parsing
   - Requires: networkx
   - Outputs: GraphML, JSON
   - Output: `/tmp/knowledge_graph_visualization/knowledge_graph_<timestamp>.graphml`

3. **knowledge_graph_interactive.py** (14.8 KB)
   - Interactive HTML visualization
   - Requires: networkx, pyvis
   - Features: drag-drop, hover tooltips, zoom/pan
   - Output: `/tmp/knowledge_graph_visualization/knowledge_graph_interactive_<timestamp>.html`

4. **demo_knowledge_graph_visualization.py** (7.6 KB)
   - Unified demo script
   - Tests all visualization tools
   - Checks dependencies automatically
   - Provides summary report

### Database Connection

- **SQLcl Path**: `/root/sqlcl/bin/sql`
- **Connection**: `openclaw/hermes@//10.10.10.130:1521/openclaw`
- **Tables Used**: `KNOWLEDGE_CONCEPTS`, `KNOWLEDGE_GRAPH`

### Test Results (2026-05-12)

```
Knowledge Concepts: 44 found ✓
Knowledge Relationships: 8 found ✓
Text Report: Generated successfully ✓
GraphML Export: Generated successfully ✓
JSON Export: Generated successfully ✓
```

---

## Critical Fix: SQL Parsing

**Problem**: Original visualizer scripts failed with `KeyError: 'CONCEPT_ID'` when parsing SQLcl output.

**Root Cause**: SQLcl returns fixed-width table format with mixed content. Simple parsing based on whitespace split produced incorrect column mapping when concept names contained spaces.

**Solution**: Implemented robust parsing in `export_graph_fixed.py`:

```python
def parse_concepts_output(output):
    """Parse concepts SQL output"""
    lines = output.split('\n')
    concepts = []
    
    for line in lines:
        parts = line.strip().split()
        if len(parts) >= 6 and parts[0].isdigit():
            try:
                concept_id = int(parts[0])
                # Reconstruct concept name from middle parts
                concept_name = ' '.join(parts[1:-4])
                concept_type = parts[-4]
                category = parts[-3]
                confidence = float(parts[-2])
                validation_status = parts[-1]
                
                concepts.append({
                    'CONCEPT_ID': concept_id,
                    'CONCEPT_NAME': concept_name,
                    # ... other fields
                })
            except (ValueError, IndexError):
                continue
```

**Key Insight**: Concept name is in the middle of the line, so we join `parts[1:-4]` to preserve spaces.

---

## Usage Patterns

### Quick Text Report (No Dependencies)

```bash
cd /root/.hermes/skills/oracle-memory-by-yhw
python3 scripts/knowledge_graph_report.py
```

### GraphML Export (Requires networkx)

```bash
pip3 install networkx
python3 scripts/export_graph_fixed.py
```

### Interactive HTML (Requires networkx + pyvis)

```bash
pip3 install networkx pyvis
python3 scripts/knowledge_graph_interactive.py
```

### Demo All Tools

```bash
python3 scripts/demo_knowledge_graph_visualization.py
```

---

## External Tool Integration

### Gephi (Recommended)

1. Download: https://gephi.org/
2. Open GraphML file
3. Apply "ForceAtlas2" layout
4. Color nodes by "concept_type" attribute
5. Size nodes by "confidence" attribute
6. Export to PNG/SVG/PDF

### Cytoscape

1. Download: https://cytoscape.org/
2. Import GraphML file
3. Use "Analyze Network" for metrics
4. Apply "Prefuse Force Directed" layout

### Python NetworkX

```python
import networkx as nx

# Load graph
G = nx.read_graphml('knowledge_graph.graphml')

# Calculate metrics
pagerank = nx.pagerank(G)
betweenness = nx.betweenness_centrality(G)

# Find top nodes
top_nodes = sorted(pagerank.items(), key=lambda x: x[1], reverse=True)[:5]
```

---

## Color Coding Scheme

### Concept Types

| Type | Color | Hex | Meaning |
|-------|-------|-----|---------|
| FACT | Red | #FF6B6B | Verified facts |
| RULE | Teal | #4ECDC4 | Rules and principles |
| PATTERN | Blue | #45B7D1 | Recognized patterns |
| EXPERIENCE | Light Salmon | #FFA07A | Learned experiences |
| PRINCIPLE | Mint | #98D8C8 | Core principles |
| CONCEPT | Yellow | #F7DC6F | General concepts |
| ENTITY | Purple | #BB8FCE | Named entities |

### Relationship Types

| Type | Color | Hex | Meaning |
|-------|-------|-----|---------|
| IS_A | Red | #E74C3C | Hierarchy |
| PART_OF | Blue | #3498DB | Composition |
| CAUSES | Orange | #E67E22 | Causality |
| ENABLES | Green | #2ECC71 | Enablement |
| CONTRADICTS | Purple | #9B59B6 | Conflict |
| SUPPORTS | Teal | #1ABC9C | Support |
| RELATED_TO | Gray | #95A5A6 | General relation |

---

## Troubleshooting

### Issue: `ModuleNotFoundError: No module named 'networkx'`

**Solution**:
```bash
pip3 install networkx
```

### Issue: `ModuleNotFoundError: No module named 'pyvis'`

**Solution**:
```bash
pip3 install networkx pyvis
```

### Issue: Key Error in parsing

**Solution**: Use `export_graph_fixed.py` which has corrected SQL parsing logic.

### Issue: No concepts found

**Check**:
```bash
echo "SELECT COUNT(*) FROM KNOWLEDGE_CONCEPTS" | \
    /root/sqlcl/bin/sql openclaw/hermes@//10.10.10.130:1521/openclaw
```

---

## Pitfalls

1. **SQLcl Output Format**: SQLcl returns fixed-width tables, not CSV. Parse by looking for patterns, not assuming position.

2. **Spaces in Names**: Concept names may contain spaces. Reconstruct from middle array parts, don't split on single space.

3. **Dependencies**: Text report requires no dependencies. GraphML needs networkx. Interactive HTML needs both networkx and pyvis.

4. **Database Connection**: Always construct connection string as `openclaw/hermes@//10.10.10.130:1521/openclaw` - note the double slash.

5. **Python Execution**: Use subprocess with bash, not direct Python Oracle calls (oracledb not available).

---

## Performance Notes

- Text report: < 1 second for 44 concepts
- GraphML export: ~2 seconds (includes networkx parsing)
- Interactive HTML: ~3-5 seconds (pyvis rendering)

For large graphs (> 1000 nodes):
1. Filter by category
2. Filter by validation status
3. Use LIMIT clause in SQL
4. Consider subgraph extraction

---

## Output Location

All visualization outputs use `/tmp/knowledge_graph_visualization/` as base directory.

Files include timestamp for versioning:
- `knowledge_graph_report_YYYYMMDD_HHMMSS.txt`
- `knowledge_graph_YYYYMMDD_HHMMSS.graphml`
- `knowledge_graph_YYYYMMDD_HHMMSS.json`
- `knowledge_graph_interactive_YYYYMMDD_HHMMSS.html`
- `knowledge_graph_stats_YYYYMMDD_HHMMSS.html`

---

## Documentation

- Main guide: `KNOWLEDGE_GRAPH_VISUALIZATION.md` (11.7 KB)
- Skill docs: `SKILL.md` (updated with visualization section)
- Implementation notes: This file

---

## Author Notes

This implementation demonstrates:
- Multi-format data export for flexibility
- Dependency-free baseline tool
- Incremental enhancement (text → graphml → interactive)
- Comprehensive documentation
- External tool ecosystem integration
- User experience (demo script for quick testing)

**Key Achievement**: Three complementary approaches (text, export, interactive) ensure usability across different scenarios and user preferences.
