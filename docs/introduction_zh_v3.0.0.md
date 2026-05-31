# AI Agent Infra with OracleDB — 社区版 v3.0.0

**版本**: v3.0.0 | **日期**: 2026-05-31 | **作者**: 尹海文 | **许可**: Apache License 2.0

> v3.0.0 是一次完全的重构和重新定位。项目从单一记忆系统演进为完整的 AI Agent 基础设施架构，推出社区版与企业版双版本策略。社区版基于 Apache 2.0 许可证，提供记忆、知识、Agent 管理、Skill 分发、加密存储等核心能力，开箱即用，自由使用。

---

## 一、项目简介

**AI Agent Infra with OracleDB** 是一套面向 AI Agent 的基础设施架构，基于 Oracle 26ai 数据库构建，为 AI Agent 提供记忆、知识、Agent 管理、Skill 分发、加密存储等核心能力。

本项目的核心设计理念是：**将 AI Agent 运行所需的一切基础设施——记忆、知识、身份、技能、安全——统一收敛于一个数据库内核之中**，利用 Oracle 26ai 的引用分区、JSON 关系对偶视图、属性图、向量搜索等原生能力，在数据库层实现基础设施的完整闭环，而非依赖外部微服务拼装。

### 核心能力矩阵

| 能力域 | 说明 |
|--------|------|
| 记忆与知识 | 5信号统一混合搜索、向量嵌入、知识图谱、记忆融合 |
| Agent 管理 | 弹性池化管理、会话生命周期、凭证加密、协作组 |
| 工作空间 | 上下文连续性、Agent 交接、会话恢复 |
| 规格驱动 | Spec 文档管理、计划关联、验证与派生 |
| Skill 分发 | ZIP 包解析、直接资源下载、Agent 自动获取 |
| Portal 用户系统 | 本地系统用户认证、注册/登录、聊天会话 |
| 加密存储 | PBKDF2+AES-256-GCM、主密钥管理、自动加密 |

---

## 二、项目起源

本项目前身为 **"Oracle AI Database Memory System"**（内部代号 `oracle-memory-by-yhw`），最初专注于 AI Agent 的记忆系统——为智能体提供短期记忆存储、长期知识沉淀和记忆融合能力。

在持续演进过程中，项目逐步扩展了 Agent 管理、工作空间、规格驱动开发、Skill 分发、Portal 用户系统等能力，从单一的记忆系统成长为覆盖 AI Agent 全生命周期的基础设施架构。v3.0.0 标志着这一转变的正式完成：

- **产品重命名**：从 "Oracle AI Database Memory System" 更名为 **"AI Agent Infra with OracleDB"**，准确反映项目的完整定位
- **双版本策略**：推出社区版（Apache 2.0）和企业版（BSL 1.1），满足不同场景需求
- **架构重构**：ENTITIES 超类型新增 SKILL 子类型分区，PL/SQL 包从 8 个扩展到 9 个

### 版本演进

| 版本 | 日期 | 里程碑 |
|------|------|--------|
| **v3.0.0** | 2026-05-31 | 完全重构与重新定位，双版本策略，社区版发布 |
| v2.3.2 | 2026-05-27 | 五信号融合检索、全文搜索、统一搜索 API |
| v2.3.0 | 2026-05-24 | 规格驱动开发、Agent 弹性管理、协作组 |
| v2.2.0 | 2026-05-20 | 工作空间与上下文连续性、JRD 可更新视图 |
| v2.1.0 | 2026-05-19 | 表分区、复合主键、属性图 API |
| v2.0.0 | 2026-05-15 | 统一架构重写、oracledb 驱动 |
| v1.0.0 | 2026-05-09 | 初始版本：知识库与属性图 |

---

## 三、双版本策略

v3.0.0 推出社区版与企业版双版本策略，满足开源社区与企业生产的不同需求。

### 社区版（Community Edition）

- **许可证**：Apache License 2.0
- **定位**：开源社区、个人研究、非生产环境、快速原型验证
- **特色**：开箱即用、Apache 2.0 自由使用、无需商业授权
- **包含**：完整的记忆与知识系统、5信号混合搜索、Agent 管理、工作空间、规格驱动开发、协作组、Harness 模板、Web 可视化、Portal 用户系统（系统用户模式）、Skill 直接分发

### 企业版（Enterprise Edition）

- **许可证**：Business Source License 1.1（BSL 1.1）
- **定位**：企业生产环境、多团队协作、安全合规场景
- **包含**：社区版全部能力 + 以下企业级扩展

### 企业版额外能力

| 企业级能力 | 说明 |
|-----------|------|
| LDAP 统一身份认证 | 对接企业 LDAP/AD 目录，支持自动注册、组角色映射、定时同步 |
| Skill 安全令牌分发 | 一次性消费令牌 + 预签名下载 URL，确保 Skill 资源分发的安全可审计 |
| 工作空间上下文审计 | 规则引擎 + embedding 语义检测，识别空闲模式、越界访问、数据泄露、token 浪费 |
| Portal LDAP 登录 | Portal 支持认证模式切换（系统用户 / LDAP 统一认证），LDAP 用户自动注册 |

### 版本对比

| 特性 | 社区版 | 企业版 |
|------|--------|--------|
| **核心基础设施** | | |
| 记忆系统与知识图谱 | ✓ | ✓ |
| 5信号统一混合搜索 | ✓ | ✓ |
| 规格驱动开发 | ✓ | ✓ |
| Agent 弹性管理 | ✓ | ✓ |
| 协作组 | ✓ | ✓ |
| 工作空间与上下文连续性 | ✓ | ✓ |
| 属性图 API | ✓ | ✓ |
| Harness 模板 | ✓ | ✓ |
| Web 可视化 Dashboard | ✓ | ✓ |
| **Portal 用户系统** | | |
| Portal 登录/注册 | ✓（系统用户） | ✓（系统用户 + LDAP） |
| Portal 聊天会话 | ✓ | ✓ |
| 会话重命名/删除 | ✓ | ✓ |
| Agent 池化分配 | ✓ | ✓ |
| **身份与认证** | | |
| 本地系统用户认证 | ✓ | ✓ |
| LDAP 统一认证 | — | ✓ |
| LDAP 自动注册 | — | ✓ |
| LDAP 同步作业 | — | ✓ |
| 管理后台隔离（仅 LOCAL） | ✓ | ✓ |
| **Skill 系统** | | |
| Skill CRUD（skill_api.py） | ✓ | ✓ |
| Skill 直接资源下载 | ✓ | ✓ |
| 安全令牌分发（skill_token_api.py） | — | ✓（企业版专属）|
| SKILL_TOKEN_CLEANUP_JOB | — | ✓ |
| **安全与加密** | | |
| 加密 config.json（数据库凭证） | ✓ | ✓ |
| 加密 LDAP BIND_CREDENTIAL | N/A | ✓ |
| 加密 AGENT_CREDENTIALS | ✓ | ✓ |
| 主密钥管理 | ✓ | ✓ |
| 数据脱敏 | ✓ | ✓ |
| **审计与合规** | | |
| 工作空间上下文审计 | — | ✓ |
| CONTEXT_AUDIT_LOG | — | ✓ |
| 审计规则引擎 + Embedding 检测 | — | ✓ |
| IDLE_PATTERN_DETECT_JOB | — | ✓ |
| **数据库对象** | | |
| 表 | 36 | 41 |
| PL/SQL 包 | 9 | 11 |
| 调度作业 | 12 | 16 |
| **许可证** | Apache 2.0 | BSL 1.1 |

---

## 四、核心架构

### 4.1 Oracle 26ai 数据库基础

本项目深度利用 Oracle 26ai 的多项原生能力，将基础设施逻辑下沉到数据库内核：

| Oracle 能力 | 应用场景 |
|-------------|---------|
| **引用分区**（Reference Partitioning） | 6 个子表（ENTITY_EDGES、KNOWLEDGE_META、SPEC_META、HARNESS_META、ENTITY_EMBEDDINGS、ENTITY_TAGS）继承 ENTITIES 的分区策略，确保父子行物理同位 |
| **JSON 关系对偶视图**（JSON Relational Duality View） | 7 个 JRD 视图（MEMORY_DV、KNOWLEDGE_DV、WORKSPACE_DV、CONTEXT_DV、SPEC_DV、COLLAB_GROUP_DV、SKILL_DV）提供 REST 友好的 JSON 文档 API，支持通过 JSON_TRANSFORM 原子部分更新 |
| **属性图**（Property Graph） | ORACLE_MEMORY_GRAPH 统一属性图，支持 SQL/PGQ 的 GRAPH_TABLE 操作符进行图遍历查询 |
| **向量搜索**（Vector Search） | ENTITY_EMBEDDINGS 表存储 VECTOR 类型嵌入，支持 VECTOR_DISTANCE 余弦相似度检索 |
| **Oracle Text** | ENTITIES_SEARCH_CTX 全文索引，MULTI_COLUMN_DATASTORE 跨列检索，CONTAINS + SCORE 全文相关性评分 |
| **LIST + RANGE 复合分区** | ENTITIES 按 ENTITY_TYPE LIST 分区 × CREATED_AT RANGE 子分区，实现类型裁剪 + 时间归档 |
| **ROW MOVEMENT** | AGENT_SESSION、TASK_PLANS 启用行迁移，状态变更时物理行在分区间移动 |

### 4.2 分层架构

```
┌───────────────────────────────────────────────────┐
│              可视化层（Visualization）            │
│  Portal（用户）+ Dashboard（管理）+ Graph Explorer│
│         server.py · templates/ · static/          │
├───────────────────────────────────────────────────┤
│              Python API 层（API Layer）           │
│  20+ 模块 · 160+ 函数 · 统一命名绑定              │
│  memory_api · knowledge_api · agent_api · ...     │
├───────────────────────────────────────────────────┤
│              数据库层（Database Layer）           │
│  36 表 · 9 PL/SQL 包 · 12 调度作业                │
│  分区 · JRD 视图 · 属性图 · 向量索引 · 全文索引   │
└───────────────────────────────────────────────────┘
```

**设计原则**：

- 数据库层（PL/SQL）处理重计算：记忆融合、知识提取、向量生成
- Python API 层提供业务逻辑：CRUD、搜索策略、Skill 解析、加密管理
- 可视化层负责交互：Portal 用户界面、Dashboard 数据管理、图探索

### 4.3 数据模型：ENTITIES 超类型 + 子类型分区

核心数据模型采用 **ENTITIES 超类型表 + ENTITY_TYPE 鉴别器 + 子类型引用分区** 的设计：

```
ENTITIES（按 ENTITY_TYPE LIST 分区，8 个分区）
  ┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬─────────┐
  │ MEMORY   │KNOWLEDGE │TASK_OUT  │EXPERI-   │ HARNESS_ │  SPEC    │  SKILL   │ OTHERS  │
  │ 记忆     │ 知识     │PUT       │ENCE      │ TEMPLATE │ 规格     │ 技能     │ 其他    │
  └──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴─────────┘
       │          │                                          │          │
  KNOWLEDGE_META  │                                    SPEC_META    SKILL_META
  (引用分区)      │                                    (引用分区)    (引用分区)
                  │
  6个引用分区子表: ENTITY_EDGES, KNOWLEDGE_META, SPEC_META,
                  HARNESS_META, ENTITY_EMBEDDINGS, ENTITY_TAGS
```

**ENTITIES 表核心列**：

| 列名 | 类型 | 说明 |
|------|------|------|
| ENTITY_ID | VARCHAR2(64) | 实体唯一标识，RAWTOHEX(SYS_GUID()) |
| ENTITY_TYPE | VARCHAR2(32) | 类型鉴别器，复合主键组成部分 |
| TITLE | VARCHAR2(512) | 实体标题 |
| CONTENT | CLOB | 实体内容（大文本） |
| SUMMARY | VARCHAR2(2000) | 摘要 |
| CATEGORY | VARCHAR2(64) | 分类 |
| IMPORTANCE | NUMBER(3,0) | 重要性评分（1-10） |
| VISIBILITY | VARCHAR2(16) | 可见性（PRIVATE/SHARED/PUBLIC） |
| WORKSPACE_ID | VARCHAR2(64) | 所属工作区 |
| CREATED_AT | TIMESTAMP | 创建时间（RANGE 子分区键） |

**复合主键设计**：`ENTITIES(ENTITY_ID, ENTITY_TYPE)`，全局唯一约束 `UK_ENTITIES_ID(ENTITY_ID)` 确保跨分区 ID 唯一性。子表通过 `PARTITION BY REFERENCE` 继承父表分区，实现父子行物理同位。

---

## 五、功能体系

### 5.1 记忆与知识系统

记忆与知识系统是项目的核心基础，提供从短期记忆到长期知识的完整生命周期管理。

#### 5信号统一混合搜索

5信号加权融合检索是本项目的核心检索能力，将五种独立信号融合为统一评分：

| 信号 | 默认权重 | 数据源 | 说明 |
|------|---------|--------|------|
| **vector** | 0.40 | ENTITY_EMBEDDINGS.EMBEDDING | 向量余弦相似度（VECTOR_DISTANCE COSINE） |
| **fulltext** | 0.25 | ENTITIES_SEARCH_CTX | Oracle Text CONTAINS + SCORE 全文相关性 |
| **relational** | 0.20 | KNOWLEDGE_META / SPEC_META / ENTITIES | 属性匹配评分（domain/category/importance） |
| **tag** | （含在 relational） | ENTITY_TAGS | 标签交集比例 + 查询词匹配 |
| **graph** | 0.15 | ENTITY_EDGES | 图邻居扩散评分（BFS 遍历，1/depth 递减） |

**融合算法**：每信号独立评分（归一化到 [0,1]）→ 加权求和 → 最终评分排序

**单 SQL 融合检索（推荐）**：`search_unified_sql()` 是本项目主推的检索方式，通过一条 SQL 语句完成五信号融合：

```sql
WITH candidates AS (
    -- 向量相似度 + 全文评分 + 元数据 JOIN
    SELECT e.ENTITY_ID, e.TITLE, e.CATEGORY, e.IMPORTANCE,
           VECTOR_DISTANCE(em.EMBEDDING, TO_VECTOR(:vec), COSINE) AS vec_distance,
           CASE WHEN CONTAINS(e.TITLE, :ftq, 1) > 0 THEN SCORE(1) ELSE 0 END AS ft_raw,
           km.DOMAIN AS km_domain, ...
    FROM ENTITY_EMBEDDINGS em
    JOIN ENTITIES e ON e.ENTITY_ID = em.ENTITY_ID
    LEFT JOIN KNOWLEDGE_META km ON ...
    ORDER BY vec_distance ASC
    FETCH FIRST :k ROWS ONLY
),
edge_counts AS (...),  -- 图连接度
tag_scores AS (...),   -- 标签匹配度
graph_prox AS (...)    -- 图邻居扩散
SELECT ..., 
       :vw * (1 - vec_distance) + :fw * ft_score + :rw * rel_score + :gw * graph_score AS final_score
FROM candidates c
LEFT JOIN edge_counts ec ON ...
ORDER BY final_score DESC
FETCH FIRST :topk ROWS ONLY
```

**技术优势**：
- **单次数据库调用**：消除 5 轮 Python-SQL 往返（candidates → tags → edges → graph → final）
- **服务端评分**：所有信号计算在数据库内核完成，避免数据传输开销
- **结果标识**：返回 `engine: "single_sql"` 字段，便于区分检索方式
- **延迟降低**：生产环境实测延迟降低 70-85%

**LLM 上下文经济学**：统一搜索 API 的深层设计动机是降低检索对 LLM 上下文的占用与污染。传统做法下，AI 智能体需要多次工具调用（先查记忆、再查知识、再查向量相似），每次调用都消耗 token 并可能用中间噪音污染上下文。统一搜索 API 将多次调用压缩为一次，保持上下文纯净，让智能体将宝贵的 token 预算留给推理与决策。

**使用建议**：
- 生产环境推荐使用 `strategy="unified_sql"`（低延迟、单次调用）
- 调试/分析场景可使用 `strategy="unified"`（多轮调用，便于观察各信号独立评分）
- 简单场景可使用 `strategy="auto"`（自动选择合适策略）

#### API 模块

| 模块 | 函数数 | 说明 |
|------|--------|------|
| embedding_api.py | 14 | 向量嵌入生成、存储、检索、五信号融合、全文搜索、单 SQL 融合 |
| search_api.py | 3 | 统一搜索入口（10 策略）+ 策略列表 + 策略说明 |

**search_api.py 10 种搜索策略**：

| 策略 | 信号 | 最佳场景 | 需要 Embedding |
|------|------|---------|---------------|
| vector | 向量相似度 | 语义/概念搜索 | 是 |
| fulltext | 全文相关性 | 精确关键词/布尔/模糊 | 否 |
| keyword | SQL LIKE | 通配符/部分匹配 | 否 |
| graph | 图关系 | 邻居探索/路径查找 | 否 |
| hybrid | 向量+全文 | 语义+词汇平衡检索 | 是 |
| unified | 五信号融合 | 综合多维检索 | 是 |
| unified_sql | 五信号融合（单 SQL） | 低延迟生产检索 | 是 |
| relational | 结构化属性 | 域/分类/难度筛选 | 否 |
| multi_type | 跨类型向量 | MEMORY/KNOWLEDGE/SPEC 联合 | 是 |
| auto | 自动检测 | 未知查询类型/便捷入口 | 视情况 |

---

### 5.2 Agent 弹性管理

Agent 弹性管理系统提供智能体的完整生命周期管理，包括注册、池化分配、会话管理、凭证加密和协作组。

#### Agent 池化状态机

```
POOL ──assign_random_pool_agent()──→ ACTIVE
  ↑                                    │
  └──────hibernate_agent()─────────────┘
         （DORMANT_AGENT_JOB 自动触发）
```

- **POOL**：无状态待分配，凭据跟随用户，可立即被分配
- **ACTIVE**：活跃工作状态，绑定 CURRENT_USER_ID
- 释放后立即回到 POOL 状态，可被重新分配

#### Agent 超时自动回收

系统通过 **DORMANT_AGENT_JOB**（每 30 分钟执行）自动检测并回收空闲 Agent：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `dormant_timeout_min` | 30 分钟 | Agent 无活跃操作超过此时间 → 自动回收到 POOL |
| `session_timeout_min` | 60 分钟 | Portal 会话超时时间 |

核心判断逻辑：`LAST_ACTIVE_AT` 超过 `dormant_timeout_min` 未更新 → 自动将 Agent 标记为 POOL 状态，清除 `CURRENT_USER_ID`。

修改超时时间：
```sql
UPDATE SYSTEM_CONFIG SET CONFIG_VALUE = '10' WHERE CONFIG_KEY = 'dormant_timeout_min';
COMMIT;
```

Portal 用户可通过 `/portal/api/agent/release` 主动释放当前 Agent，触发 `hibernate_agent()` 立即将 Agent 回收到 POOL。

#### 会话管理

- 创建会话时关联 OWNER_USER_ID、WORKSPACE_ID、PREDECESSOR_SESSION_ID
- PREDECESSOR_SESSION_ID 形成会话链表，支持 Agent 交接链回溯
- AGENT_SESSION 按 LIST(IS_ACTIVE) + RANGE(START_TIME) 分区，启用 ROW MOVEMENT

#### 凭证加密

- AGENT_CREDENTIALS.CREDENTIAL_VALUE 使用主密钥加密存储
- `issue_credential()` / `verify_credential()` 使用 `encrypt_section()` / `decrypt_section()`
- 修复了此前 ReversibleEncryption 使用随机密钥导致不可逆的缺陷

#### 协作组

- Mode C：组级共享工作空间 + LEAD/CONTRIBUTOR 个人工作空间
- OBSERVER 角色无个人工作空间
- OPEN / MODERATED / RESTRICTED 共享策略

#### API 模块

| 模块 | 函数数 | 说明 |
|------|--------|------|
| agent_api.py | 17+ | Agent 注册、会话管理、凭证加密、池化分配、休眠/唤醒、协作 |

---

### 5.3 工作空间与上下文

工作空间系统提供 Agent 的上下文连续性保障，支持跨会话的状态保持和 Agent 交接。

#### 核心概念

- **WORKSPACES**：顶层容器，生命周期 ACTIVE → PAUSED → COMPLETED/ABANDONED
- **WORKSPACE_CONTEXT**：版本链式上下文条目，通过 PARENT_CONTEXT_ID 形成链表
- **WORKSPACE_ALIAS**：工作空间别名，用于会话自动命名
- **上下文类型**：CHECKPOINT、HANDOFF、SUMMARY、ERROR_STATE、AUTO_SAVE、CHAT_MESSAGE

#### 上下文连续性

- 新聊天会话自动创建 AGENT_SESSION + CONVERSATION WORKSPACE
- 首条用户消息通过 WORKSPACE_ALIAS 自动命名会话（取前 60 字符）
- Agent 交接时创建 HANDOFF 上下文，新会话通过 PREDECESSOR_SESSION_ID 链接

#### API 模块

| 模块 | 函数数 | 说明 |
|------|--------|------|
| workspace_api.py | 14 | 工作区生命周期、上下文链、Agent 交接、恢复、任务关联 |

---

### 5.4 规格驱动开发

规格驱动开发（Spec Driven Development, SDD）提供从规格文档到任务计划的完整链路。

- **SPEC_META**：引用分区子表，存储规格版本、状态、验收标准、约束、范围、复杂度
- **SPEC_PLAN_LINKS**：规格与计划的多对多关联，LINK_TYPE 包括 DRIVES、VALIDATES、CONSTRAINS、EXTENDS
- 规格支持派生（PARENT_SPEC_ID）和验证

#### API 模块

| 模块 | 函数数 | 说明 |
|------|--------|------|
| spec_api.py | 10 | 规格创建、查询、更新、验证、派生、计划关联 |

---

### 5.5 模板引擎

Harness 模板系统提供可复用的 Agent 执行蓝图，支持变量替换和模板继承。

- **HARNESS_META**：引用分区子表，存储模板版本、输入/输出 Schema、执行模式
- **5 个内置模板**：Research Analyst、Code Assistant、Data Analyst、Task Planner、Security Auditor
- 模板生命周期：DRAFT → PUBLISHED → DEPRECATED → ARCHIVED
- 支持继承（DERIVES_FROM）和变量替换

#### API 模块

| 模块 | 函数数 | 说明 |
|------|--------|------|
| harness_api.py | 6 | 模板创建、查询、实例化、派生、验证 |

---

### 5.6 Portal 用户系统

Portal 用户系统提供面向终端用户的独立页面系统，与管理后台 Dashboard 分离。社区版仅支持本地系统用户认证。

#### Portal 登录页（/portal/login）

- **注册/登录双标签页**：切换式界面，仅限本地系统用户注册与登录
- **认证模式**：系统用户认证（社区版仅此模式，无 LDAP 选项）
- 注册查重：查询 SYSTEM_USERS（不区分大小写）
- 右上角"进入管理页面"按钮

#### Portal 聊天页（/portal/chat）

- **侧边栏**：用户信息（用户名 + 认证类型）、会话列表（重命名/删除）、新建聊天按钮
- **主区域**：聊天消息、输入框、模拟关键词回复
- **会话管理**：创建/切换/重命名/删除聊天会话
- **自动命名**：新会话默认 "New Chat"，首条消息后自动重命名为前 60 字符（通过 WORKSPACE_ALIAS）
- **Agent 生命周期**：POOL → ACTIVE（分配） → POOL（释放）

#### 管理后台（/login）

- 仅 LOCAL 用户可访问 Admin Dashboard
- 所有数据管理页面不变

---

### 5.7 Skill 存储与分发

Skill 存储与分发系统提供数据库支持的 Skill 注册中心。社区版采用直接资源下载模式，Agent 可直接获取 Skill 资源文件，无需令牌流程。

#### 数据库表

| 表名 | 类型 | 说明 |
|------|------|------|
| SKILL_META | 引用分区（继承 ENTITIES） | Skill 元数据，含 SKILL_DESCRIPTION、RESOURCE_SERVER_HOST |

**SKILL_META 核心列**：

| 列名 | 类型 | 说明 |
|------|------|------|
| ENTITY_ID | VARCHAR2(64) | 复合主键，FK 到 ENTITIES |
| SKILL_NAME | VARCHAR2(256) | 技能名称 |
| SKILL_VERSION | VARCHAR2(32) | 版本号，默认 1.0.0 |
| SKILL_TYPE | VARCHAR2(32) | BUILTIN / CUSTOM |
| SKILL_FORMAT | VARCHAR2(32) | TEXT / SCRIPT / HYBRID |
| TEXT_CONTENT | CLOB | SKILL.md 文本内容 |
| RESOURCE_URI | VARCHAR2(2048) | 资源文件相对路径 |
| RESOURCE_SERVER_HOST | VARCHAR2(512) | 服务器主机名 + IP |
| SKILL_DESCRIPTION | CLOB | 技能描述 |
| RUNTIME | VARCHAR2(32) | PYTHON / BASH / NODE / OTHER |
| PARAMETERS | JSON | 参数定义 |
| DEPENDENCIES | JSON | 依赖列表 |

#### JRD 视图

**SKILL_DV**：JSON 关系对偶视图，提供 Skill 数据的可更新 JSON 文档 API。

#### Python API

| 模块 | 函数数 | 说明 |
|------|--------|------|
| skill_api.py | 9 | 注册、查询、列表、更新（支持 title+description）、删除、依赖解析、验证、废弃、资源上传 |
| skill_parser.py | — | ZIP 包解析器，三级元数据优先级：`_meta.json` > YAML frontmatter > `## Metadata` |
| skill_storage.py | — | 文件存储抽象层，服务器主机名+IP 追踪、ZIP 重打包下载 |
| skill_acquire_api.py | 4 | Agent 技能发现与获取：发现、获取文本、获取资源、获取完整包 |

**skill_parser.py 元数据解析优先级**：

1. `_meta.json`（ClawHub 标准：slug + version）
2. SKILL.md YAML frontmatter（name + description）
3. SKILL.md `## Metadata` 区段（键值对格式）

**skill_api.py 9 个函数**：

| 函数 | 说明 |
|------|------|
| `register_skill()` | 注册新 Skill，解析 ZIP 包元数据 |
| `get_skill()` | 获取 Skill 详情（含文本内容） |
| `list_skills()` | 列出 Skill（支持过滤） |
| `update_skill()` | 更新 Skill（支持 title + description） |
| `delete_skill()` | 删除 Skill 及关联资源 |
| `resolve_skill_dependencies()` | 解析 Skill 依赖关系 |
| `validate_skill()` | 验证 Skill 完整性 |
| `deprecate_skill()` | 废弃 Skill |
| `upload_skill_resource()` | 上传 Skill 资源文件 |

**skill_acquire_api.py 4 个函数**：

| 函数 | 说明 |
|------|------|
| `discover_skills()` | 按类型/运行时/格式/关键词发现可用 Skill |
| `acquire_skill_text()` | 获取 SKILL.md 文本内容 |
| `acquire_skill_resource()` | 获取资源 ZIP 包（社区版直接下载） |
| `acquire_skill_full()` | 获取完整 Skill 包（文本 + 资源） |

#### Skill 创建流程（Dashboard）

两步创建流程：

1. **上传 ZIP** → 自动解析元数据（skill_parser.py）→ 可编辑表单 → 确认创建
2. **资源下载**：Dashboard 直接下载，Agent API 直接获取（无需令牌）

#### 社区版直接下载模式

社区版中，Agent 获取 Skill 资源采用直接下载模式：

```
1. discover_skills()           → 发现可用 Skill
2. acquire_skill_text()        → 获取 SKILL.md 文本内容
3. acquire_skill_resource()    → 直接下载资源 ZIP 包
4. acquire_skill_full()        → 一步获取完整包（文本 + 资源）
```

资源文件命名格式：`{skill_name}-{version}.zip`

---

### 5.8 加密凭证系统

加密凭证系统确保敏感信息在静态存储时始终处于加密状态，覆盖数据库连接和 Agent 凭证两大场景。

#### 加密方案

| 组件 | 说明 |
|------|------|
| connection_crypto.py | 配置加密/解密/密钥轮换/自动加密 |
| ConfigEncryption（security.py） | PBKDF2-HMAC-SHA512 密钥派生 + 认证加密（AES-256-GCM 风格） |
| encrypt_config.py | CLI 工具：encrypt、decrypt、rotate-key、verify |

**加密参数**：

| 参数 | 值 |
|------|-----|
| 密钥派生 | PBKDF2-HMAC-SHA512，210,000 次迭代 |
| 加密算法 | AES-256-GCM 风格认证加密 |
| 盐值长度 | 32 字节 |
| Nonce 长度 | 12 字节 |
| 密钥长度 | 32 字节（256 位） |
| 认证标签 | 16 字节（SHA-256 前 16 字节） |

#### 主密钥管理

主密钥按以下优先级解析：

1. **环境变量** `MASTER_DB_KEY`（推荐，Base64 编码）
2. **密钥文件** `~/.oracle-infra/master.key`（权限 0o600）
3. **自动生成** 随机 32 字节密钥，保存到密钥文件

#### 加密覆盖范围

| 加密对象 | 说明 |
|---------|------|
| config.json 数据库凭证 | `user`/`password`/`dsn` 加密为 `_encrypted` blob，首次运行自动加密 |
| AGENT_CREDENTIALS.CREDENTIAL_VALUE | `issue_credential()` / `verify_credential()` 使用主密钥加密 |

#### 自动加密流程

1. 首次运行时检测 config.json 中的明文数据库凭证
2. 提取敏感键值（user、password、dsn）
3. 使用 `encrypt_section()` 加密为 `_encrypted` blob
4. 移除明文键值，写入加密 blob
5. 设置文件权限为 0o600

---

## 六、Agent 获取 Skill 的完整指南

Agent 获取 Skill 是 Skill 分发系统的核心使用场景，社区版采用直接下载模式，支持 Python API 和 HTTP 端点两种方式。

### Python API 方式

#### 步骤 1：发现 Skill

```python
from scripts.lib.skill_acquire_api import discover_skills

skills = discover_skills(
    skill_type="CUSTOM",
    runtime="PYTHON",
    keyword="data analysis"
)

for skill in skills:
    print(f"  {skill['skill_name']} v{skill['skill_version']} - {skill.get('skill_description', '')}")
```

#### 步骤 2：获取 Skill 文本内容

```python
from scripts.lib.skill_acquire_api import acquire_skill_text

skill_text = acquire_skill_text("ENT_xxxx")

print(f"技能: {skill_text['skill_name']}")
print(f"描述: {skill_text['description']}")
print(f"内容:\n{skill_text['text_content']}")
print(f"有资源文件: {skill_text['has_resource']}")
```

#### 步骤 3：获取 Skill 资源（直接下载）

```python
from scripts.lib.skill_acquire_api import acquire_skill_resource

resource = acquire_skill_resource("ENT_xxxx")

if resource.get('resource_zip'):
    with open(f"{resource['skill_name']}.zip", "wb") as f:
        f.write(resource['resource_zip'])
    print(f"资源已下载: {resource['skill_name']}.zip")
```

#### 一步获取完整 Skill 包

```python
from scripts.lib.skill_acquire_api import acquire_skill_full

full_skill = acquire_skill_full("ENT_xxxx")

print(f"技能: {full_skill['skill_name']}")
print(f"文本内容: {full_skill['text_content'][:200]}")
if full_skill.get('resource_zip'):
    with open(f"{full_skill['skill_name']}.zip", "wb") as f:
        f.write(full_skill['resource_zip'])
```

### HTTP 端点方式

Agent 可通过 HTTP 端点获取 Skill，无需认证：

#### 发现 Skill

```
GET /api/agent/skills?keyword=data+analysis&type=CUSTOM
```

响应示例：

```json
{
  "skills": [
    {
      "entity_id": "ENT_xxxx",
      "skill_name": "data-analyzer",
      "skill_version": "1.2.0",
      "skill_type": "CUSTOM",
      "skill_description": "数据分析技能",
      "runtime": "PYTHON"
    }
  ]
}
```

#### 获取 Skill 文本元数据

```
GET /api/agent/skill/{id}/acquire
```

响应示例：

```json
{
  "skill_id": "ENT_xxxx",
  "skill_name": "data-analyzer",
  "skill_version": "1.2.0",
  "text_content": "# Data Analyzer\n\n...",
  "description": "数据分析技能",
  "has_resource": true,
  "resource_size": 15360
}
```

#### 直接下载 Skill 资源

```
GET /api/agent/skill/{id}/resource
```

响应：ZIP 文件二进制流，Content-Type 为 `application/zip`，Content-Disposition 为 `attachment; filename="{skill_name}-{version}.zip"`。

---

## 七、Web 可视化系统

Web 可视化系统提供 9+ 页面的管理界面，分为 Portal（用户面向）和 Dashboard（管理面向）两套独立页面系统。

### 页面列表

| 页面 | URL | 功能 |
|------|-----|------|
| Portal 登录 | /portal/login | 注册/登录双标签页（系统用户认证） |
| Portal 聊天 | /portal/chat | 聊天会话、Agent 池化分配、自动命名 |
| 知识 | /knowledge | 列表/图双视图，行内详情展开 |
| 记忆 | /memory | 列表/图双视图，类别过滤 |
| 智能体 | /agents | Bootstrap Tabs：注册表/会话/协作 |
| 任务 | /tasks | Accordion 折叠，步骤详情，工具 I/O |
| 工作区 | /workspaces | 可展开详情行，上下文时间线 |
| 图探索 | /graph | 统计卡片，搜索，vis-network，详情面板 |
| 规格 | /specs | 规格列表，计划关联，详情视图 |
| 协作 | /collab | 组列表，成员管理，共享记忆 |
| 技能 | /skills | Skill 列表，资源管理，直接下载 |

### UI 特性

| 特性 | 说明 |
|------|------|
| 行内详情展开 | 所有列表页支持行内行展开，替代右侧面板 |
| 中英双语切换 | data-zh/data-en 属性，语言偏好 localStorage 持久化 |
| 暗色主题 | CSS 变量驱动的统一暗色主题 |
| 客户端分页 | PAGE_SIZE=30，Prev/Next + 页码按钮 |
| 粘性表头 | position:sticky，滚动时表头固定 |
| 5 分钟自动登出 | 侧边栏倒计时，60 秒警告，30 秒标题闪烁 |
| ID 悬停全文 | 截断 ID 悬停显示完整内容 |

### 登录凭据

- Dashboard 登录：admin / admin123
- Portal 登录：注册系统用户后登录

---

## 八、数据库对象统计

### 8.1 表（36 张）

| 分类 | 表名 | 说明 | 分区方式 |
|------|------|------|---------|
| **核心** | ENTITIES | 统一实体存储（8 种类型） | LIST(ENTITY_TYPE) + RANGE(CREATED_AT) |
| | ENTITY_EDGES | 有向关系边 | 引用分区（继承 ENTITIES） |
| | KNOWLEDGE_META | 知识元数据 | 引用分区（继承 ENTITIES） |
| | SPEC_META | 规格元数据 | 引用分区（继承 ENTITIES） |
| | SKILL_META | 技能元数据 | 引用分区（继承 ENTITIES） |
| | HARNESS_META | Harness 模板元数据 | 引用分区（继承 ENTITIES） |
| | ENTITY_EMBEDDINGS | 向量嵌入 | 引用分区（继承 ENTITIES） |
| | ENTITY_TAGS | 标签关联 | 引用分区（继承 ENTITIES） |
| | TAGS | 标签定义 | 非分区 |
| **系统** | SYSTEM_USERS | 用户账户 | 非分区 |
| | SYSTEM_CONFIG | 键值配置 | 非分区 |
| **智能体** | AGENT_REGISTRY | 智能体定义 | 非分区 |
| | AGENT_CREDENTIALS | 加密凭据 | 非分区 |
| | AGENT_SESSION | 会话 + 交接链 | LIST(IS_ACTIVE) + RANGE(START_TIME) |
| | ENTITY_ACCESS_LOG | 实体访问审计 | RANGE(ACCESS_TIME) + HASH(AGENT_ID) |
| | AGENT_PERMISSION_LOG | 权限变更审计 | 非分区 |
| **协作** | AGENT_COLLABORATION | 智能体间协作 | 非分区 |
| | COLLAB_GROUPS | 协作组 | 非分区 |
| | COLLAB_GROUP_MEMBERS | 组成员 | 非分区 |
| **工作区** | WORKSPACES | 工作区生命周期 | 非分区 |
| | WORKSPACE_CONTEXT | 上下文链 | 非分区 |
| | WORKSPACE_TASKS | 工作区↔任务关联 | 非分区 |
| **任务** | TASK_PLANS | 任务计划 | LIST(STATUS) + RANGE(CREATED_AT) |
| | TASK_STEPS | 计划步骤 | 引用分区（继承 TASK_PLANS） |
| | TASK_CONTEXT_SNAPSHOTS | 步骤执行上下文 | 非分区 |
| | TASK_TOOL_CALLS | 工具调用记录 | 非分区 |
| | TASK_DEPENDENCIES | 步骤依赖图 | 非分区 |
| **规格** | SPEC_PLAN_LINKS | 规格↔计划多对多 | 非分区 |

### 8.2 PL/SQL 包（9 个）

| 包名 | 子程序数 | 说明 |
|------|---------|------|
| MEMORY_FUSION_ENGINE | 7 | 记忆融合、知识提取、衰减 |
| KNOWLEDGE_BASE_API | 5 | 知识管理、审查调度 |
| AGENT_PERMISSION_MANAGER | 5 | 权限管理、会话清理 |
| SESSION_CLEANUP | 4 | 会话清理、日志归档 |
| WORKSPACE_MANAGER | 10 | 工作区管理、上下文维护 |
| SPEC_MANAGER | 8 | 规格管理、计划关联 |
| COLLAB_GROUP_MANAGER | 6 | 协作组管理 |
| EMBEDDING_MANAGER | 5 | Embedding 生成、查询、余弦相似度 |
| SKILL_MANAGER | 6 | Skill 注册、更新、废弃、依赖解析 |

### 8.3 调度作业（12 个）

| 作业 | 调度 | 说明 |
|------|------|------|
| MEMORY_FUSION_JOB | 每日 02:00 | 融合相似记忆 + 衰减旧记忆 |
| KNOWLEDGE_EXTRACTION_JOB | 每日 03:00 | 从记忆提取知识 |
| KNOWLEDGE_REVIEW_JOB | 每日 06:00 | 知识审查与验证 |
| SESSION_CLEANUP_JOB | 每 30 分钟 | 清理过期会话 |
| ACCESS_LOG_PURGE_JOB | 每周日 04:00 | 清理访问日志（90 天） |
| ENTITY_ARCHIVE_JOB | 每周日 05:00 | 归档旧实体（180 天） |
| COLLAB_EXPIRY_JOB | 每日 00:30 | 处理协作请求 |
| WORKSPACE_CLEANUP_JOB | 每日 04:00 | 归档废弃工作区（30 天） |
| STALE_WORKSPACE_DETECT_JOB | 每小时 | 检测无活跃会话的工作区 |
| DORMANT_AGENT_JOB | 每 30 分钟 | 超时 Agent 自动设为 POOL 状态 |
| CREDENTIAL_CLEANUP_JOB | 每日 02:00 | 清理过期凭据 |
| EMBEDDING_GENERATION_JOB | 每 2 小时 | 自动生成缺失的 embedding |

### 8.4 JRD 双重视图（7 个）

| 视图 | 模式 | 根表 | 嵌套对象 |
|------|------|------|----------|
| MEMORY_DV | 可更新 | ENTITIES(MEMORY) | ENTITY_TAGS, ENTITY_EDGES |
| KNOWLEDGE_DV | 可更新 | ENTITIES(KNOWLEDGE) | KNOWLEDGE_META, ENTITY_TAGS, ENTITY_EDGES |
| WORKSPACE_DV | 可更新 | WORKSPACES | WORKSPACE_TASKS |
| CONTEXT_DV | 只读 | WORKSPACE_CONTEXT | — |
| SPEC_DV | 可更新 | ENTITIES(SPEC) | SPEC_META, SPEC_PLAN_LINKS |
| COLLAB_GROUP_DV | 可更新 | COLLAB_GROUPS | COLLAB_GROUP_MEMBERS |
| SKILL_DV | 可更新 | ENTITIES(SKILL) | SKILL_META |

---

## 九、快速开始

### ⚠️ 部署前安全检查（必读）

**在运行任何部署脚本之前，必须检查数据库是否已有部署。重新初始化将销毁所有已有数据（Agent、会话、知识、工作空间、Skill）。**

```python
from lib.deploy_api import check_deployment

result = check_deployment()
if result["deployed"]:
    # 数据库已有部署，切勿重新运行部署脚本！
    # 仅注册 Skill 即可：
    from lib.skill_api import register_skill
else:
    # 安全，可以全新部署
    pass
```

HTTP 端点（公开，无需认证）：
```bash
curl http://localhost:8000/api/agent/deployment-check
```

SQL 脚本 `1_schema.sql` 已内置保护：检测到 `SYSTEM_CONFIG.schema_version` 存在时自动中止部署。

### 前置条件

- Oracle Database 23ai+（在 26ai 上测试）
- Python 3.8+，需安装 `oracledb` 包
- SQLcl 26.1+（用于 SQL 脚本部署）

### 1. 部署 Schema

```bash
sql user/password@//host:port/service @scripts/deploy/1_schema.sql
sql user/password@//host:port/service @scripts/deploy/2_api.sql
sql user/password@//host:port/service @scripts/deploy/3_jobs.sql
sql user/password@//host:port/service @scripts/deploy/4_harness_templates.sql
```

### 2. 安装 Python 依赖

```bash
pip install oracledb
```

### 3. 配置

编辑 `config.json`，数据库凭证将在首次运行时自动加密：

```bash
# 方式 A：环境变量（推荐）
export MASTER_DB_KEY=$(python3 -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())")
export MEMORY_DB_USER=<db_user>
export MEMORY_DB_PASSWORD=<db_password>
export MEMORY_DB_DSN=<db_host>:<db_port>/<db_service>

# 方式 B：编辑 config.json（首次运行时自动加密）
```

或手动加密：

```bash
cd scripts && python -m tools.encrypt_config encrypt
```

### 4. 运行测试

```bash
cd scripts && python -m tests.test_all
```

### 5. 启动可视化服务器

```bash
./start_web_server.sh start    # 启动（守护进程模式）
./start_web_server.sh status   # 查看状态
./start_web_server.sh stop     # 停止
# 访问 http://<web_host>:<web_port> — 登录: admin / admin123
```

---

## 十、许可证与作者

### 许可证

**社区版**：Apache License 2.0

- 自由使用、修改、分发
- 无商业限制
- 适用于开源社区、个人研究、非生产环境

详见 [LICENSE](../LICENSE)

### 作者

**尹海文（Haiwen Yin）**

- GitHub: [https://github.com/Haiwen-Yin](https://github.com/Haiwen-Yin)
- 博客: [https://blog.csdn.net/yhw1809](https://blog.csdn.net/yhw1809)
