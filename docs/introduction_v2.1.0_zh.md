# Oracle AI 数据库记忆系统 v2.1.0

> **统一 AI 智能体记忆系统** — 基于知识图谱、多智能体协作、任务规划、Harness 模板引擎、属性图 API 与 Web 可视化，构建于 Oracle 23ai 之上。

**版本**: v2.1.0 | **日期**: 2026-05-19 | **作者**: 尹海文 | **许可**: Apache License 2.0

---

## 一、项目概述

Oracle AI 数据库记忆系统是一个面向 AI 智能体（Agent）的企业级记忆管理平台，旨在为 AI 应用提供结构化的长期记忆、知识图谱、多智能体协作与任务编排能力。系统以 Oracle 23ai 数据库为核心存储，利用其原生 JSON、向量检索、属性图（Property Graph）、JSON-Relational Duality View 和表分区等高级特性，实现了一个统一、高效、可扩展的智能体记忆基础设施。

**v2.1.0 是 v2.0.0 的重大升级**，引入复合主键、表分区、属性图 Python API、规范化标签体系和 VARCHAR2(64) ID 生成，与 v2.0.0 不兼容，无就地升级路径，需全新部署。

---

## 二、v2.1.0 核心变更 — 相对 v2.0 的突破

| v2.0 痛点 | v2.1 方案 | 效果 |
|-----------|----------|------|
| 单列主键无法分区 | 复合主键 (ENTITY_ID, ENTITY_TYPE) | 支持引用分区，父子行物理同位 |
| 大表全表扫描 | LIST+RANGE/RANGE+HASH 分区 | 按类型/时间裁剪，查询性能提升 |
| 无图遍历 Python API | graph_api.py 9 个函数 + GRAPH_TABLE | 原生图遍历、路径查找、社区检测 |
| JSON TAGS 列不可索引 | TAGS + ENTITY_TAGS 规范化表 | 标签查询可索引，支持按标签过滤 |
| NUMBER 自增 ID | VARCHAR2(64) + RAWTOHEX(SYS_GUID()) | 全局唯一、无需序列、跨系统可合并 |
| 会话/计划状态变更无物理分区移动 | ROW MOVEMENT 启用 | 状态变更自动行迁移到对应分区 |
| 无知识复查调度 | KNOWLEDGE_REVIEW_JOB | 每日自动安排间隔复查 |
| HARNESS 元数据不表达输入输出 | INPUT_SCHEMA/OUTPUT_SCHEMA (JSON Schema) | 模板输入输出结构化定义 |
| ACCESSIBLE_TO JSON 数组复杂 | 简化为 PRIVATE/SHARED/PUBLIC | 可见性模型更清晰，协作走 AGENT_COLLABORATION |

---

## 三、核心架构

### 3.1 统一实体模型（复合主键）

v2.1 将 ENTITIES 的主键从单列 ENTITY_ID 升级为复合主键 (ENTITY_ID, ENTITY_TYPE)：

```
ENTITIES（统一实体表，复合 PK: ENTITY_ID + ENTITY_TYPE）
  ├── MEMORY          — 短期智能体记忆
  ├── KNOWLEDGE       — 长期验证知识（扩展: KNOWLEDGE_META）
  ├── TASK_OUTPUT     — 任务执行输出
  ├── EXPERIENCE      — 学习经验与启发式规则
  ├── HARNESS_TEMPLATE — 可复用智能体执行蓝图（扩展: HARNESS_META）
  └── OTHER           — 其他类型（兜底）
```

**v2.1 列变更**：

| v2.0 列 | v2.1 列 | 说明 |
|---------|---------|------|
| NAME | TITLE | 重命名 |
| PRIORITY | IMPORTANCE | 重命名，范围 1-10 |
| TAGS (JSON) | *(移除)* | 拆分为 TAGS + ENTITY_TAGS 表 |
| METADATA (JSON) | *(移除)* | 仅保留在 ENTITY_EDGES |
| ACCESSIBLE_TO (JSON) | *(移除)* | 简化为 PRIVATE/SHARED/PUBLIC |
| DESCRIPTION | *(移除)* | 由 SUMMARY 替代 |
| *(新增)* | SUMMARY | VARCHAR2(2000) 实体摘要 |
| *(新增)* | SOURCE_AGENT | VARCHAR2(64) 创建智能体 |
| *(新增)* | RETRIEVAL_COUNT | NUMBER(10,0) 访问计数 |
| *(新增)* | IMPORTANCE | NUMBER(3,0) 1-10 重要度 |

### 3.2 统一边模型（复合主键 + SOURCE_TYPE）

ENTITY_EDGES 主键升级为 (EDGE_ID, SOURCE_ID)，新增 SOURCE_TYPE 列：

- FK: (SOURCE_ID, SOURCE_TYPE) 引用 ENTITIES(ENTITY_ID, ENTITY_TYPE)
- 10 种边类型：DEPENDS_ON, RELATED_TO, DERIVED_FROM, CAUSES, ENABLES, PREVENTS, SIMILAR_TO, EVOLVED_FROM, CONTRADICTS, SUPPORTS
- STRENGTH (0-1) 和 CONFIDENCE (0-1) 支持加权图遍历
- METADATA (JSON) 仅保留在边表

### 3.3 复合主键与反规范化 ENTITY_TYPE

v2.1 使用复合主键启用引用分区。ENTITY_TYPE 列反规范化到所有引用 ENTITIES 的子表：

| 子表 | 主键 | 外键 | 反规范化列 |
|------|------|------|-----------|
| ENTITY_EDGES | (EDGE_ID, SOURCE_ID) | (SOURCE_ID, SOURCE_TYPE) | SOURCE_TYPE |
| KNOWLEDGE_META | (ENTITY_ID, ENTITY_TYPE) | (ENTITY_ID, ENTITY_TYPE) | ENTITY_TYPE |
| ENTITY_EMBEDDINGS | (ENTITY_ID, ENTITY_TYPE) | (ENTITY_ID, ENTITY_TYPE) | ENTITY_TYPE |
| HARNESS_META | (ENTITY_ID, ENTITY_TYPE) | (ENTITY_ID, ENTITY_TYPE) | ENTITY_TYPE |
| ENTITY_TAGS | (ENTITY_ID, ENTITY_TYPE, TAG_ID) | (ENTITY_ID, ENTITY_TYPE) | ENTITY_TYPE |

全局唯一约束（UK_*）确保 ID 在复合主键场景下的唯一性：
UK_ENTITIES_ID, UK_EDGES_ID, UK_TASK_PLANS_ID, UK_TASK_STEPS_ID, UK_ACCESS_LOG_ID

### 3.4 表分区架构

#### ENTITIES — LIST + RANGE（6 分区 x 7 子分区 = 42 子分区）

```
PARTITION BY LIST (ENTITY_TYPE)
  P_MEMORY, P_KNOWLEDGE, P_TASK_OUTPUT, P_EXPERIENCE, P_HARNESS, P_OTHERS

SUBPARTITION BY RANGE (CREATED_AT)
  SP_2026Q1 .. SP_2027Q2, SP_FUTURE
```

按 ENTITY_TYPE 过滤的查询只需扫描单个分区；按时间范围查询进一步裁剪到子分区。

#### 引用分区表（5 张表）

ENTITY_EDGES, KNOWLEDGE_META, ENTITY_EMBEDDINGS, HARNESS_META, ENTITY_TAGS 通过 PARTITION BY REFERENCE (FK_...) 继承父表 ENTITIES 的分区，确保子行与父行物理同位。

#### AGENT_SESSION — LIST + RANGE

```
PARTITION BY LIST (IS_ACTIVE): P_ACTIVE('Y'), P_INACTIVE('N')
SUBPARTITION BY RANGE (START_TIME): 季度子分区
```

启用 ROW MOVEMENT — 会话从活跃变为非活跃时，行自动迁移到非活跃分区。

#### TASK_PLANS — LIST + RANGE

```
PARTITION BY LIST (STATUS): P_ACTIVE(PENDING/RUNNING/BLOCKED), P_TERMINAL(SUCCESS/FAILED/CANCELLED)
SUBPARTITION BY RANGE (CREATED_AT): 季度子分区
```

启用 ROW MOVEMENT — 计划状态变更导致行在活跃/终态分区之间迁移。TASK_STEPS 通过引用分区继承。

#### ENTITY_ACCESS_LOG — RANGE + HASH

```
PARTITION BY RANGE (ACCESS_TIME): 月分区
SUBPARTITION BY HASH (AGENT_ID) SUBPARTITIONS 4
```

优化时间范围扫描，哈希子分区支持高并发智能体访问模式。

#### 非分区表

AGENT_REGISTRY, AGENT_PERMISSION_LOG, AGENT_COLLABORATION, TASK_CONTEXT_SNAPSHOTS, TASK_TOOL_CALLS, TASK_DEPENDENCIES, TAGS, SYSTEM_CONFIG, SYSTEM_USERS。

### 3.5 辅助表体系

| 表名 | 分区策略 | 用途 |
|------|---------|------|
| ENTITIES | LIST+RANGE | 统一实体表 |
| ENTITY_EDGES | REFERENCE | 统一有向边表 |
| KNOWLEDGE_META | REFERENCE | 知识扩展元数据（领域、主题、难度、间隔复查） |
| ENTITY_EMBEDDINGS | REFERENCE | 语义向量嵌入 VECTOR |
| HARNESS_META | REFERENCE | 模板版本、输入/输出模式、执行模式 |
| TAGS | 非分区 | 标签定义（TAG_ID, TAG_NAME, TAG_GROUP） |
| ENTITY_TAGS | REFERENCE | 实体-标签关联（规范化替代 JSON TAGS） |
| AGENT_REGISTRY | 非分区 | 智能体身份、能力、配置 |
| AGENT_SESSION | LIST+RANGE | 会话追踪与上下文（ROW MOVEMENT） |
| ENTITY_ACCESS_LOG | RANGE+HASH | 实体访问审计日志 |
| AGENT_PERMISSION_LOG | 非分区 | 权限变更审计（GRANT/REVOKE/DENY） |
| AGENT_COLLABORATION | 非分区 | 跨智能体协作链接 |
| TASK_PLANS | LIST+RANGE | 多步骤任务定义（ROW MOVEMENT） |
| TASK_STEPS | REFERENCE | 计划步骤与状态追踪（含 PLAN_STATUS） |
| TASK_CONTEXT_SNAPSHOTS | 非分区 | 断点/恢复快照 |
| TASK_TOOL_CALLS | 非分区 | 工具调用审计 |
| TASK_DEPENDENCIES | 非分区 | 跨计划依赖图 |
| SYSTEM_CONFIG | 非分区 | 系统配置 |
| SYSTEM_USERS | 非分区 | 系统用户与角色 |

### 3.6 属性图与对偶视图

- **ORACLE_MEMORY_GRAPH**：统一属性图，使用复合顶点键 (ENTITY_ID, ENTITY_TYPE)，支持 SQL PGQ 语法跨类型图遍历
- **MEMORY_DV / KNOWLEDGE_DV**：JSON-Relational Duality Views，使用复合 _id: {entity_id, entity_type}，JOIN 条件基于 (SOURCE_ID = ENTITY_ID AND SOURCE_TYPE = ENTITY_TYPE)

---

## 四、属性图 Python API（graph_api.py）

v2.1 新增 9 个图遍历函数，全部基于 GRAPH_TABLE SQL 操作符：

| 函数 | 功能 | GRAPH_TABLE 模式 |
|------|------|-----------------|
| get_neighbors() | 获取邻居节点 | MATCH (a)-[e]->(b) 单跳遍历 |
| get_reachable() | 多跳可达性 | MATCH (a)-[e]->{1,N}(v) 多跳模式 |
| get_shortest_path() | 最短路径 | 逐步展开匹配（最多 6 跳） |
| find_similar_entities() | 图近邻相似 | 基于图距离的相似性发现 |
| get_entity_context() | 实体上下文 | 直接 SQL + 邻居分组 |
| get_graph_stats() | 图统计 | 顶点/边计数、度分布、类型分布 |
| get_subgraph() | 子图提取 | 按实体 ID 列表提取，含中间节点 |
| find_communities() | 社区检测 | 高连接度实体聚类 |
| graph_search() | 图感知搜索 | MATCH (a) WHERE ... 条件过滤 |

---

## 五、4 阶段 SQL 部署

### Phase 1: 1_schema.sql — 模式层
- 19 张表（6 分区 + 5 引用分区 + 8 非分区）
- 复合主键、全局唯一约束、ROW MOVEMENT
- LIST+RANGE / RANGE+HASH / REFERENCE 分区策略
- safe_ddl/safe_idx 辅助函数确保幂等重跑
- **破坏性**：自动删除所有已有表（CASCADE CONSTRAINTS PURGE）
- VARCHAR2(64) ID 生成 via RAWTOHEX(SYS_GUID())
- 所有枚举列加 CHECK 约束
- 种子数据：SYSTEM_CONFIG（版本 2.1.0）、SYSTEM_USERS（admin 账户）

### Phase 2: 2_api.sql — PL/SQL API 层
4 个 PL/SQL 包，使用 JSON_OBJECT VALUE 语法、RAWTOHEX(SYS_GUID()) ID、复合主键 JOIN：

| 包名 | 功能 |
|------|------|
| MEMORY_FUSION_ENGINE | 合并相似记忆、提取知识、衰减重要度 |
| KNOWLEDGE_BASE_API | 间隔复查调度/记录、知识血统查询 |
| AGENT_PERMISSION_MANAGER | 访问控制、会话清理、协作处理 |
| SESSION_CLEANUP | 清除日志、归档实体、标签计数 |

### Phase 3: 3_jobs.sql — 调度层
7 个自动化调度作业（v2.1 新增 KNOWLEDGE_REVIEW_JOB）：

| 作业 | 调度 | 功能 |
|------|------|------|
| MEMORY_FUSION_JOB | 每天 02:00 | 融合相似记忆 + 重要度衰减 |
| KNOWLEDGE_EXTRACTION_JOB | 每天 03:00 | 从记忆模式提取知识 |
| KNOWLEDGE_REVIEW_JOB | 每天 06:00 | 安排知识间隔复查 |
| SESSION_CLEANUP_JOB | 每 30 分钟 | 清理过期会话 |
| ACCESS_LOG_PURGE_JOB | 每周日 04:00 | 清除 90 天以上日志 |
| ENTITY_ARCHIVE_JOB | 每周日 05:00 | 归档 180 天以上低重要度记忆 |
| COLLAB_EXPIRY_JOB | 每天 00:30 | 处理协作请求 |

### Phase 4: 4_harness_templates.sql — Harness 模板层
- 种子化 5 个内置模板
- HARNESS_META 含 INPUT_SCHEMA/OUTPUT_SCHEMA (JSON Schema) 和 EXECUTION_MODE
- 使用 MERGE 确保幂等

---

## 六、Python API 库

### 6.1 模块结构（9 个模块）

| 模块 | 功能 |
|------|------|
| config.py | 统一配置数据类，支持环境变量覆盖 |
| connection.py | oracledb 连接池管理（延迟初始化、线程安全） |
| memory_api.py | 记忆 CRUD + 标签管理（ENTITIES, ENTITY_TYPE=MEMORY） |
| knowledge_api.py | 知识 CRUD + 边操作 + 间隔复查 + 标签 |
| graph_api.py | **v2.1 新增** 属性图遍历（9 个函数，GRAPH_TABLE 操作符） |
| agent_api.py | 智能体注册、会话、协作、访问日志 |
| task_plan_api.py | 任务计划、步骤（含 PLAN_STATUS）、快照、工具调用、依赖 |
| security.py | 数据脱敏、可逆加密、密码哈希 |
| harness_api.py | 模板 CRUD、实例化、变量提取（8 个公开函数） |

### 6.2 ID 生成策略

所有 ID 均为 VARCHAR2(64)，通过 RAWTOHEX(SYS_GUID()) 生成 32 字符十六进制字符串：

| 前缀 | 用途 | 示例 |
|------|------|------|
| *(无前缀)* | 实体 ID | A1B2C3D4E5F6... |
| E_ | 边 ID | E_A1B2C3D4... |
| SES_ | 会话 ID | SES_A1B2C3D4... |
| LOG_ | 访问日志 ID | LOG_A1B2C3D4... |
| COL_ | 协作 ID | COL_A1B2C3D4... |
| PLAN_ | 计划 ID | PLAN_A1B2C3D4... |
| STEP_ | 步骤 ID | STEP_A1B2C3D4... |
| HARNESS_ | 模板 ID | HARNESS_A1B2C3D4... |

### 6.3 代码示例

```python
from scripts.lib.memory_api import create_memory, get_memory, add_memory_tags
from scripts.lib.knowledge_api import create_knowledge, add_edge
from scripts.lib.graph_api import get_neighbors, get_shortest_path, graph_search
from scripts.lib.agent_api import register_agent, create_session
from scripts.lib.harness_api import create_harness_template, instantiate_harness_template

# 创建记忆
mid = create_memory("会议纪要", "讨论了 v2.1 分区方案", category="meeting", importance=8)

# 添加标签
add_memory_tags(mid, ["架构", "分区", "v2.1"])

# 创建知识概念
kid = create_knowledge("分区架构模式", "复合主键 + 引用分区", domain="architecture", importance=9)

# 建立关联（需要 source_type 参数）
eid = add_edge(mid, 'MEMORY', kid, 'DERIVED_FROM', strength=0.9)

# 图遍历
neighbors = get_neighbors(kid, direction="both", min_strength=0.5)

# 图搜索
results = graph_search(keyword="分区", entity_type="KNOWLEDGE", min_importance=7)

# Harness 模板
tpl_id = create_harness_template(
    title="数据分析师",
    content="你是{role}，请分析{data}",
    execution_mode="PARALLEL",
)
instance_id = instantiate_harness_template(tpl_id, {"role": "金融分析师", "data": "Q3财报"}, "agent-1")
```

### 6.4 设计模式

- 所有查询使用绑定变量（防 SQL 注入）
- INSERT...RETURNING 返回 VARCHAR2(64) ID
- execute_query 返回 List[Dict[str, Any]]（列名作键）
- MERGE INTO 实现幂等注册
- _sanitize_decimals() 处理 oracledb 返回的 decimal.Decimal
- _fix_encoding() 修正 oracledb thin 模式的 UTF-8 双重编码
- composite FK 操作需要 ENTITY_TYPE/SOURCE_TYPE/PLAN_STATUS 参数

---

## 七、Harness 模板系统

### 7.1 HARNESS_META（v2.1 重构）

| 列 | 类型 | 说明 |
|----|------|------|
| ENTITY_ID | VARCHAR2(64) | FK 到 ENTITIES |
| ENTITY_TYPE | VARCHAR2(32) | 反规范化，固定 HARNESS_TEMPLATE |
| TEMPLATE_VERSION | VARCHAR2(32) | 模板版本号 |
| INPUT_SCHEMA | JSON | JSON Schema 定义输入变量 |
| OUTPUT_SCHEMA | JSON | JSON Schema 定义输出格式 |
| EXECUTION_MODE | VARCHAR2(32) | SEQUENTIAL / PARALLEL / CONDITIONAL |

**v2.1 移除**：VARIABLES (JSON)、TEMPLATE_STATUS、CHANGELOG (JSON)

### 7.2 关键能力

| 能力 | 说明 |
|------|------|
| **JSON Schema 输入/输出** | INPUT_SCHEMA 定义变量（类型、默认值、必填），OUTPUT_SCHEMA 定义输出格式 |
| **3 种执行模式** | SEQUENTIAL（顺序）、PARALLEL（并行）、CONDITIONAL（条件分支） |
| **变量替换** | {variable} 在实例化时解析替换 |
| **实例化** | 创建 TASK_OUTPUT 实体 + USES_HARNESS 边 |
| **模板验证** | get_template_with_variables() 从 INPUT_SCHEMA 提取变量定义 |
| **5 个内置模板** | Research Analyst, Code Assistant, Data Analyst, Task Planner, Security Auditor |

### 7.3 内置模板

| 模板 | 类别 | 执行模式 | 输入变量 |
|------|------|---------|---------|
| Research Analyst | research | SEQUENTIAL | role, domain, objective, query |
| Code Assistant | development | SEQUENTIAL | role, language, guidelines, task |
| Data Analyst | analytics | PARALLEL | role, focus_area, data_query |
| Task Planner | orchestration | CONDITIONAL | role, constraints, objective |
| Security Auditor | security | SEQUENTIAL | role, policies, action |

### 7.4 Python API（8 个函数）

| 函数 | 功能 |
|------|------|
| create_harness_template() | 创建模板（含 INPUT_SCHEMA/OUTPUT_SCHEMA/EXECUTION_MODE） |
| get_harness_template() | 获取模板完整元数据 + HARNESS_META |
| update_harness_template() | 更新实体字段和模板元数据 |
| delete_harness_template() | 删除模板 + HARNESS_META |
| list_harness_templates() | 列表（支持类别/执行模式过滤） |
| get_template_with_variables() | 从 INPUT_SCHEMA 提取变量定义 |
| instantiate_harness_template() | 实例化模板（变量替换 + 创建实例实体） |
| count_harness_templates() | 计数 |

---

## 八、安全模块

### 8.1 数据脱敏（DataMaskingService）

- **7 种模式类型**：email、phone、credit_card、ssn、api_key、ip_address、jwt_token
- **4 种上下文级别**：LOGGING、DEBUGGING、ANALYTICS、SHARING
- 确定性匹配顺序（credit_card 优先于 phone，避免误匹配）

### 8.2 可逆加密（ReversibleEncryption）

- PBKDF2 密钥派生 + XOR 加密
- 长度前缀编码（替代零字节填充）
- 安全密钥轮换：先全部解密，再用新密钥重新加密

### 8.3 密码哈希

- PBKDF2-HMAC-SHA256，可配置迭代次数（默认 100,000 次）

### 8.4 可见性模型（v2.1 简化）

| 级别 | 访问 |
|------|------|
| PRIVATE | 仅 OWNED_BY_AGENT |
| SHARED | 所有注册智能体 |
| PUBLIC | 无限制（v2.1 新增，替代 v2.0 COLLABORATIVE） |

跨智能体共享通过 AGENT_COLLABORATION 表管理。

---

## 九、Web 可视化系统

### 9.1 五页面仪表板

| 页面 | 路由 | 功能 |
|------|------|------|
| **知识图谱** | /knowledge | vis.js 交互式图，展示 KNOWLEDGE 实体及关系 |
| **记忆内容** | /memory | vis.js 交互式图，展示 MEMORY 实体及连接 |
| **智能体协作** | /agents | 3 标签页仪表板：智能体注册表、活跃会话、协作请求 |
| **任务计划** | /tasks | 状态过滤、关键词搜索、手风琴式计划列表 |
| **属性图** | /graph | 图 API 浏览器：实体上下文、路径、社区 |

### 9.2 图 API 端点（v2.1 新增）

| 端点 | 功能 |
|------|------|
| /api/graph/neighbors | 实体邻居查询 |
| /api/graph/path | 最短路径查找 |
| /api/graph/context | 实体上下文与邻居分组 |
| /api/graph/stats | 图统计信息 |
| /api/graph/search | 图感知搜索 |
| /api/graph/subgraph | 子图提取 |
| /api/graph/communities | 社区检测 |

### 9.3 UI 列名更新（v2.1）

| v2.0 标签 | v2.1 标签 |
|-----------|-----------|
| Name | Title |
| Priority | Importance (1-10) |
| Tags (JSON) | Tags (表) |
| Metadata | *(移除)* |
| Accessible To | *(移除)* |

新增显示：Summary、Source Agent、Retrieval Count、Execution Mode

---

## 十、测试体系

### 10.1 测试覆盖

```
Oracle Memory System v2.1.0 - 全量测试套件
============================================================
  连接测试:    6/6  通过
  记忆测试:    7/7  通过
  知识测试:    7/7  通过
  智能体测试:  7/7  通过
  安全测试:   10/10 通过
  Harness 测试:   10/10 通过
  图测试:      8/8  通过  ← v2.1 新增
Overall: ALL PASSED (49 tests)
```

### 10.2 测试模块

| 测试文件 | 用例数 | 覆盖范围 |
|------|------|------|
| test_connection.py | 6 | 连接池创建、获取、释放、查询、异常处理 |
| test_memory.py | 7 | 创建/读取/更新/删除/搜索/标签 |
| test_knowledge.py | 7 | 概念创建/关系/图遍历/元数据/标签 |
| test_agent.py | 7 | 注册/会话/协作/权限/审计 |
| test_security.py | 10 | 脱敏/加密/哈希/密钥轮换 |
| test_harness.py | 10 | CRUD/实例化/变量提取 |
| test_graph.py | 8 | **v2.1 新增** 邻居/路径/上下文/统计/搜索/子图/社区 |

---

## 十一、开发过程中修复的关键 Bug

| Bug | 修复方案 |
|------|------|
| oracledb 返回 decimal.Decimal 无法 JSON 序列化 | 添加 _sanitize_decimals() 和 _sanitize_val() 自动转换 |
| oracledb thin 模式双重编码 UTF-8 中文 | 添加 _fix_encoding() 智能检测 CJK vs Latin-1 范围字符 |
| viz_server 任何请求崩溃导致服务器死亡 | do_GET -> _do_GET 异常包装器隔离单请求失败 |
| 手机号正则匹配到信用卡号 | 调整模式匹配顺序（credit_card 优先） |
| Oracle 保留字 :desc 作为绑定变量 | 重命名为 :adesc |
| SYSTIMESTAMP 作为绑定变量传入 | 改为 SQL 字面量 |
| 密钥轮换损坏密文 | 先全部解密，再用新密钥重新加密 |
| 可逆加密零字节填充问题 | 改用长度前缀编码 |
| 分区键更新导致 ORA-14402 | 在 AGENT_SESSION/TASK_PLANS/TASK_STEPS 启用 ROW MOVEMENT |
| 引用分区 FK 不兼容导致 ORA-14650 | 确保子表 FK 引用父表复合主键（含分区键列） |

---

## 十二、快速开始

```bash
# 1. 克隆项目
git clone https://github.com/Haiwen-Yin/oracle-memory-system.git
cd oracle-memory-system

# 2. 部署数据库（4 阶段）
sql user/password@//host:port/service @scripts/deploy/1_schema.sql
sql user/password@//host:port/service @scripts/deploy/2_api.sql
sql user/password@//host:port/service @scripts/deploy/3_jobs.sql
sql user/password@//host:port/service @scripts/deploy/4_harness_templates.sql

# 3. 安装 Python 依赖
pip install oracledb

# 4. 配置
export MEMORY_DB_USER=openclaw
export MEMORY_DB_PASSWORD=hermes
export MEMORY_DB_DSN=10.10.10.130:1521/openclaw

# 5. 运行测试
cd scripts && python -m tests.test_all

# 6. 启动 Web 服务器
./start_web_server.sh start
# 访问 http://localhost:8000
# 登录：admin / admin123
```

---

## 十三、文档索引

| 文档 | 说明 |
|------|------|
| [SKILL.md](../SKILL.md) | 精简技能概览 |
| [architecture.md](architecture.md) | 架构设计与分区策略 |
| [api-reference.md](api-reference.md) | Python + PL/SQL API 参考（含 graph_api） |
| [deployment.md](deployment.md) | 部署指南与分区维护 |
| [migration.md](migration.md) | v2.0 -> v2.1 迁移指南 |
| [security.md](security.md) | 安全特性与配置 |
| [visualization.md](visualization.md) | Web 可视化服务器指南（含图 API 端点） |
| [harness.md](harness.md) | Harness 模板系统指南 |
| [minimum-privileges.md](minimum-privileges.md) | 最小数据库用户权限 |

---

## 十四、版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| **v2.1.0** | 2026-05-19 | 复合主键、表分区、属性图 API、规范化标签、VARCHAR2(64) ID |
| v2.0.0 | 2026-05-15 | 完全重写：统一架构、oracledb 驱动、4 阶段部署、Harness 模板 |
| v1.1.0 | 2026-05-12 | Web 可视化、会话安全、双语 UI |
| v1.0.0 | 2026-05-10 | 生产发布：知识库、属性图、多智能体 |
| v0.5.1 | 2026-05-08 | 增强会话管理 |
| v0.5.0 | 2026-05-06 | 多智能体协作框架 |
| v0.4.0 | 2026-05-02 | 任务计划系统 |
| v0.3.x | 2026-04-28 | 核心记忆系统 |

---

## 许可

Apache License 2.0 — Copyright (c) 2026 尹海文
