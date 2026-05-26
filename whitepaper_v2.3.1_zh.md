# Oracle AI 数据库记忆系统 v2.3.1

## 产品白皮书

| 项目 | 详情 |
|------|------|
| **产品名称** | Oracle AI 数据库记忆系统 (Oracle AI Database Memory System) |
| **版本** | 2.3.1 |
| **发布日期** | 2026年5月 |
| **作者** | 尹海文 |
| **许可证** | Apache 2.0 |
| **数据库** | Oracle 26ai |
| **Python** | 3.14.5 / oracledb 4.0.0 thin mode |

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [产品定位与核心价值](#2-产品定位与核心价值)
3. [系统架构](#3-系统架构)
4. [统一实体模型](#4-统一实体模型)
5. [记忆引擎](#5-记忆引擎)
6. [知识图谱](#6-知识图谱)
7. [规格驱动开发](#7-规格驱动开发)
8. [智能体弹性管理](#8-智能体弹性管理)
9. [协作组](#9-协作组)
10. [工作空间与上下文连续性](#10-工作空间与上下文连续性)
11. [任务规划引擎](#11-任务规划引擎)
12. [Harness模板系统](#12-harness模板系统)
13. [属性图API](#13-属性图api)
14. [五信号融合检索](#14-五信号融合检索)
15. [全文搜索引擎](#15-全文搜索引擎)
16. [统一搜索API](#16-统一搜索api)
17. [安全体系](#17-安全体系)
18. [企业级数据架构](#18-企业级数据架构)
19. [自动化运维](#19-自动化运维)
20. [可视化控制台](#20-可视化控制台)
21. [API参考](#21-api参考)
22. [部署与运维](#22-部署与运维)
23. [版本演进](#23-版本演进)
24. [术语表](#24-术语表)

---

## 1. 执行摘要

Oracle AI 数据库记忆系统是一款面向AI智能体的企业级记忆与知识管理平台，基于Oracle 26ai数据库构建，为AI代理提供持久化记忆、结构化知识管理、规格驱动开发、弹性智能体调度与多智能体协作等核心能力。

传统AI代理面临记忆遗忘、知识孤岛、协作困难等根本性挑战。本系统通过统一实体模型、引用分区、JRD可更新视图等Oracle 26ai原生特性，构建了一套完整的企业级解决方案。

**v2.3.1版本四大核心升级：**

- **向量检索修复与增强**：修复v2.0.0架构重写过程中遗漏的embedding生成与向量检索能力，新增EMBEDDING_MANAGER PL/SQL包与自动embedding生成调度作业
- **五信号融合检索**：vector(0.4) + fulltext(0.25) + relational(0.2) + tag + graph(0.15) 五信号加权融合，每信号独立评分+加权求和，可调权重与多维过滤
- **全文搜索引擎**：基于Oracle Text CONTEXT索引的全文检索，支持布尔运算、模糊匹配、词干搜索，跨TITLE+CONTENT列检索
- **统一搜索API**：10种搜索策略的统一入口（vector/fulltext/keyword/graph/hybrid/unified/relational/multi_type/auto），自动策略检测

**系统规模一览：**

| 指标 | 数值 |
|------|------|
| 数据库表 | 27 |
| JRD视图 | 6 |
| PL/SQL包 | 8 |
| 调度作业 | 12 |
| Python模块 | 15 |
| API函数 | 130+ |
| 搜索策略 | 9 |
| 测试通过率 | 183/183 (100%) |
| 可视化页面 | 9 |


---

## 2. 产品定位与核心价值

### 2.1 AI Agent记忆的核心痛点

当前AI智能体在实际生产环境中，不仅面临基本的功能缺失，更深层次的问题源于**纯文本存储架构**的固有缺陷。AI Agent的记忆并非简单的文本信息堆砌，还涵盖上下文关联、元数据属性等多维信息；且单条记忆并非孤立存在，而是嵌套在完整的记忆链路与知识图谱体系之中。

#### 2.1.1 纯文本存储架构的底层缺陷

| 缺陷 | 描述 |
|------|------|
| **容量与维护瓶颈** | 当单条记忆文本容量过大，或记忆文件数量累积到一定规模后，AI Agent难以快速检索匹配有效信息，同时记忆文件的日常管理与维护成本大幅攀升 |
| **关联检索能力薄弱** | 无法建立标准化索引体系，难以实现关联记忆的高效精准检索 |
| **Token资源消耗过高** | 冗余繁杂的记忆读写操作直接增加Token消耗量，频繁的记忆调度还会挤占上下文窗口资源，造成上下文信息冗余与污染 |
| **规模化场景适配性不足** | 在多Agent协同、企业级落地场景中，记忆来源维度更多样、读写调用频次更高，纯文本文件的存储与调用架构无法承载高并发、高负载的记忆存取需求 |

#### 2.1.2 生产环境中的六大挑战

| 痛点 | 描述 |
|------|------|
| **记忆遗忘** | AI代理的对话记忆随会话结束而丢失，无法形成长期经验积累 |
| **知识孤岛** | 不同代理、不同项目间的知识无法互通，形成信息壁垒 |
| **规格缺失** | AI代理缺乏行为规格约束，输出质量不可控、不可验证 |
| **资源浪费** | 空闲代理持续占用资源，无法弹性伸缩，运维成本居高不下 |
| **协作困难** | 多代理间缺乏结构化协作机制，任务交接混乱 |
| **上下文断裂** | 会话切换或代理变更时，上下文丢失，工作连续性被破坏 |

#### 2.1.3 数据库架构的根本性优势

引入数据库架构重构AI Agent记忆存储体系，是解决纯文本记忆短板的最优路径：

| 优势 | 说明 |
|------|------|
| **多模态一体化存储** | 现代多模数据库不仅支持传统关系型标量数据存储，还可兼容AI Agent所需的长文本、JSON结构化数据，并能依托图数据能力搭建完整的记忆链路与知识图谱 |
| **多维度数据互补增强** | 借助标量业务数据为向量检索做辅助标注，弥补向量检索精准度不足的短板，提升记忆匹配准确率 |
| **统一接口与混合查询能力** | 通过SQL语句实现多模态数据联合混合查询，以最简操作流程高效调取所需记忆数据 |
| **高性能与高可用保障** | 数据库原生支持高并发读写能力，搭配成熟的集群高可用架构，提供稳定、高效的底层支撑 |

### 2.2 六大核心能力

| 能力 | 描述 |
|------|------|
| **持久化记忆** | 跨会话的记忆存储与检索，支持强化、衰减、融合与归档的完整生命周期 |
| **结构化知识** | 领域知识的结构化管理，支持间隔复习、知识溯源与矛盾检测 |
| **五信号融合检索** | vector+fulltext+relational+tag+graph五信号加权融合，可调权重，每信号独立评分 |
| **全文搜索引擎** | Oracle Text CONTEXT索引，布尔/模糊/词干搜索，跨TITLE+CONTENT列 |
| **统一搜索API** | 9种搜索策略统一入口，自动策略检测，AI智能体可按需选择或自动匹配 |
| **规格驱动开发** | 规格为一等实体，驱动计划生成与验证闭环，确保输出符合规格约束 |
| **弹性智能体管理** | DORMANT休眠与POOL池化双模式，配合凭据体系实现资源弹性调度 |
| **协作组** | 组级共享+个人隔离的双层工作空间，三级共享策略满足不同协作场景 |
| **上下文连续性** | 基于工作空间的追加式上下文链，支持检查点、交接、摘要等多类型上下文 |

### 2.3 技术优势

| 优势 | 说明 |
|------|------|
| **原生Oracle 26ai** | 充分利用JSON/OSON、属性图、引用分区、JRD Duality Views等最新特性 |
| **统一实体模型** | 7种实体类型共享单表，消除数据孤岛，统一访问接口 |
| **引用分区** | 6张子表通过引用分区自动继承父表分区策略，零维护成本 |
| **JRD可更新视图** | 6个REST Duality View，前端可直接通过REST API写入数据库 |
| **纯Python thin模式** | oracledb 4.0.0 thin mode，无Oracle客户端依赖，跨平台部署 |
| **183/183测试覆盖** | 全量测试通过，覆盖所有核心能力路径 |
| **9种搜索策略** | 统一搜索API入口，自动策略检测，覆盖向量/全文/图/混合/融合等全部检索场景 |


---

## 3. 系统架构

### 3.1 四层架构

```
+---------------------------------------------------------------------+
|                    可视化层 (Visualization)	                      |
|      Knowledge | Memory | Agents | Tasks | Workspaces | ...	      |
|                    8 页面 · 暗色主题 · 中英双语	                  |
+---------------------------------------------------------------------+
|                  Python API 层 (Business Logic)                     |
|      memory_api | knowledge_api | agent_api | spec_api | ...        |
|                     12 模块 · 99+ API 函数	                      |
+---------------------------------------------------------------------+
|                  Oracle 26ai 层 (Data & Logic)                      |
|   27 Tables | 6 JRD Views | 8 PL/SQL Packages | Graph | Oracle Text |
|              引用分区 · 复合主键 · OSON · 属性图	                  |
+---------------------------------------------------------------------+
|                     调度层 (Scheduler)                              |
|      MEMORY_FUSION_JOB | DECAY_JOB | DORMANT_AGENT_JOB | ...        |
|                    11 调度作业 · 自动化运维	                      |
+---------------------------------------------------------------------+
```

### 3.2 数据流

```
+------------+    +-----------+    +-----------+    +------------+    +-----------+
|  Agent     |--->|  Memory   |--->|  Fusion   |--->| Knowledge  |--->|  Graph    |
| Interaction|    |  Store    |    |  Engine   |    | Extraction |    |  Building |
+------------+    +-----------+    +-----------+    +------------+    +-----------+
      |                 |                |                |                 |
      v                 v                v                v                 v
  SESSION          ENTITIES        MEMORY_FUSION    KNOWLEDGE_META    ENTITY_EDGES
  ENTITIES         (MEMORY)        ENGINE pkg       ENTITIES(KNOW)    PROPERTY GRAPH
                   WORKSPACE
                   CONTEXT
```

**数据流说明：**

1. **智能体交互**：Agent通过API创建会话，产生交互数据
2. **记忆存储**：交互内容作为MEMORY类型实体存入ENTITIES表
3. **记忆融合**：MEMORY_FUSION_ENGINE定期执行相似记忆融合、衰减与知识提取
4. **知识提取**：高重要性记忆（IMPORTANCE>7）自动提取为KNOWLEDGE实体
5. **图谱构建**：实体间关系通过ENTITY_EDGES建立，形成属性图

### 3.3 部署架构

```
+------------------+     HTTP/REST      +------------------+
|                  | <----------------> |                  |
|   Browser        |     :8000          |  Python App      |
|   (Dashboard)    |                    |  Server          |
|                  |                    |  (server.py)     |
+------------------+                    +--------+---------+
                                                 |
                                         oracledb 4.0.0
                                         thin mode
                                                 |
                                        +--------v---------+
                                        |                  |
                                        |  Oracle 26ai     |
                                        |  Database        |
                                        |                  |
                                        +------------------+
```


---

## 4. 统一实体模型

### 4.1 设计理念

统一实体模型是本系统的核心设计范式。通过单表多态（Single-Table Polymorphism），将7种实体类型统一存储于表中，终于数据孤岛，提供统一的访问接口与关系构建基础。

```
+-----------------------------------------------------------+
|                      ENTITIES                             |
|                                                           |
|  MEMORY ----------+                                       |
|  KNOWLEDGE -------+                                       |
|  TASK_OUTPUT -----+--- 共享列 + 类型专属扩展列 + JSON扩展 |
|  EXPERIENCE ------+                                       |
|  HARNESS_TEMPLATE +                                       |
|  SPEC ------------+                                       |
|  OTHER -----------+                                       |
+-----------------------------------------------------------+
        |
        | 引用分区 (Reference Partitioning)
        +--> MEMORY_META
        +--> KNOWLEDGE_META
        +--> SPEC_META
        +--> HARNESS_META
        +--> TAGS
        +--> ENTITY_EDGES
```

### 4.2 核心表结构

**ENTITIES表完整列定义：**

| 列名 | 类型 | 说明 |
|------|------|------|
| ENTITY_ID | VARCHAR2(64) | 实体唯一标识，RAWTOHEX(SYS_GUID()) |
| ENTITY_TYPE | VARCHAR2(20) | 实体类型：MEMORY/KNOWLEDGE/TASK_OUTPUT/EXPERIENCE/HARNESS_TEMPLATE/SPEC/OTHER |
| TITLE | VARCHAR2(500) | 实体标题 |
| CONTENT | CLOB | 实体内容 |
| IMPORTANCE | NUMBER(3) | 重要性评分 (1-10) |
| VISIBILITY | VARCHAR2(10) | 可见性：PRIVATE/SHARED/PUBLIC |
| WORKSPACE_ID | VARCHAR2(64) | 所属工作空间 |
| CREATED_BY | VARCHAR2(100) | 创建者 |
| CREATED_AT | TIMESTAMP | 创建时间 |
| UPDATED_AT | TIMESTAMP | 更新时间 |
| ENTITY_DATA | JSON | JSON灵活扩展字段（OSON格式） |

**复合主键：** `(ENTITY_ID, ENTITY_TYPE)`

### 4.3 引用分区机制

复合主键`(ENTITY_ID, ENTITY_TYPE)`使得6张子表可以通过引用分区（Reference Partitioning）自动继承ENTITIES的分区策略：

```sql
CREATE TABLE MEMORY_META (
    ENTITY_ID     VARCHAR2(64) NOT NULL,
    ENTITY_TYPE   VARCHAR2(20) DEFAULT 'MEMORY',
    CONSTRAINT FK_MEMORY_META_ENTITY
        FOREIGN KEY (ENTITY_ID, ENTITY_TYPE)
        REFERENCES ENTITIES (ENTITY_ID, ENTITY_TYPE)
) PARTITION BY REFERENCE FK_MEMORY_META_ENTITY;
```

**引用分区的优势：**

- 零维护：子表分区自动随父表创建/维护
- 分区裁剪：查询自动跳过无关分区，性能最优
- 数据一致性：父表与子表数据物理对齐

### 4.4 全局唯一约束

为支持跨分区外键引用，ENTITIES表设置了全局唯一约束：

```sql
ALTER TABLE ENTITIES ADD CONSTRAINT UK_ENTITIES_ID UNIQUE (ENTITY_ID);
```

此约束确保`ENTITY_EDGES`等关系表可以仅通过`ENTITY_ID`引用任意类型的实体，无需包含`ENTITY_TYPE`。

### 4.5 JSON灵活扩展

`ENTITY_DATA`列使用Oracle 26ai原生JSON/OSON类型，提供灵活的半结构化扩展能力：

```python
# 写入时使用 json.dumps()
entity_data = json.dumps({
    source: conversation,
    confidence: 0.95,
    tags_auto: [oracle, memory]
})

# 读取时自动转为 dict
data = row['ENTITY_DATA']  # -> dict

# 更新时使用 JSON_TRANSFORM（非 JSON_MERGEPATCH）
sql = """
UPDATE ENTITIES
SET ENTITY_DATA = JSON_TRANSFORM(ENTITY_DATA, SET '$.status' = 'active')
WHERE ENTITY_ID = :eid
"""
```


---

## 5. 记忆引擎

### 5.1 记忆生命周期

```
+---------+    +-----------+    +---------+    +--------+    +---------+
| Create  |--->| Reinforce |--->|  Decay  |--->|  Fuse  |--->| Archive |
| (创建)  |    | (强化)    |    | (衰减)  |    | (融合) |    | (归档)  |
+---------+    +-----------+    +---------+    +--------+    +---------+
     |               |               |             |              |
     v               v               v             v              v
 IMPORTANCE=5   IMPORTANCE+1    x0.95因子     相似记忆合并   IMPORTANCE=1
 新实体创建      重复记忆增强    每日衰减       知识提取       标记归档
```

**各阶段说明：**

| 阶段 | 触发条件 | 效果 |
|------|---------|------|
| **Create** | Agent首次产生记忆 | 创建MEMORY实体，默认IMPORTANCE=5 |
| **Reinforce** | 重复或相似记忆出现 | IMPORTANCE递增，更新UPDATED_AT |
| **Decay** | MEMORY_DECAY_JOB每日执行 | IMPORTANCE x 0.95，低于阈值则归档 |
| **Fuse** | MEMORY_FUSION_JOB定期执行 | 合并相似记忆，提取高重要性知识 |
| **Archive** | IMPORTANCE降至阈值以下 | 标记为归档状态，不再参与衰减 |

### 5.2 MEMORY_FUSION_ENGINE包

```sql
CREATE OR REPLACE PACKAGE MEMORY_FUSION_ENGINE AS
    PROCEDURE fuse_similar_memories(
        p_similarity_threshold IN NUMBER DEFAULT 0.8
    );
    PROCEDURE decay_old_memories(
        p_decay_factor IN NUMBER DEFAULT 0.95
    );
    PROCEDURE extract_knowledge_from_memories(
        p_importance_threshold IN NUMBER DEFAULT 7
    );
    FUNCTION get_fusion_stats RETURN SYS_REFCURSOR;
END MEMORY_FUSION_ENGINE;
```

**核心算法：**

- **fuse_similar_memories**：基于标题与内容的相似度匹配（阈值0.8），合并为单一记忆，保留最高IMPORTANCE
- **decay_old_memories**：每日对非归档记忆执行 `IMPORTANCE = IMPORTANCE x 0.95`，低于1.0则归档
- **extract_knowledge_from_memories**：IMPORTANCE>7的记忆自动提取为KNOWLEDGE实体，创建DERIVES_FROM边

### 5.3 记忆搜索

系统提供从基础关键词搜索到五信号融合检索的完整搜索体系（详见第14-16节）：

**搜索能力层次：**

| 层次 | 方法 | 说明 |
|------|------|------|
| L1 关键词 | search_memories | SQL LIKE基础检索 |
| L2 向量 | search_similar | 语义相似度检索（VECTOR_DISTANCE COSINE） |
| L3 全文 | search_fulltext | Oracle Text CONTAINS+SCORE全文检索 |
| L4 混合 | search_hybrid | 向量+关键词双信号混合 |
| L5 融合 | search_unified | 五信号加权融合检索 |
| L6 统一 | search_api.search | 10策略统一入口+自动检测 |

**文本记忆检索的LLM上下文挑战：**

传统AI记忆系统在检索环节存在一个被普遍忽视的痛点——**上下文污染**。当AI智能体需要获取记忆或知识时，若检索过程本身需要多次工具调用（先查记忆、再查知识、再查标签、再查关联），每一次调用的请求与响应都会占用LLM的上下文窗口。更严重的是，这些中间步骤的冗余信息会"污染"上下文，导致：

- **Token浪费**：多次调用产生大量中间结果，挤占可用于推理的有效token空间。一个5步检索流程可能消耗上千token仅用于工具调用开销，而非实际内容
- **信噪比下降**：中间步骤的调试信息、部分结果、空响应等噪音混入上下文，干扰LLM对最终结果的判断与推理
- **上下文窗口溢出**：长对话场景下，累积的检索开销可能导致上下文窗口溢出，迫使系统丢弃最早的对话内容，破坏会话连续性

v2.3.1的五信号融合检索与统一搜索API正是为解决此痛点而设计：**用一条查询语句获取全部所需数据，将多次工具调用压缩为一次**，最大限度减少token开销和上下文污染风险（详见第14.3节和第16.1节）。

基础关键词搜索示例：

```python
results = search_memories(
    keyword="Oracle分区",
    category="技术",
    visibility="SHARED",
    workspace_id="ws-001",
    importance_min=7,
    limit=20
)
```

### 5.4 可见性模型

```
+----------------------------------------------+
|              VISIBILITY 模型                 |
|                                              |
|  PRIVATE  -- 仅创建者可见                    |
|  SHARED   -- 同工作空间内可见                |
|  PUBLIC   -- 全局可见                        |
|                                              |
|  访问控制检查：                              |
|  1. PUBLIC -> 直接允许                       |
|  2. SHARED -> 验证 WORKSPACE_ID 匹配         |
|  3. PRIVATE -> 验证 CREATED_BY 匹配          |
+----------------------------------------------+
```

### 5.5 标签系统

标签使用`MERGE INTO`实现幂等写入：

```sql
MERGE INTO TAGS t
USING (SELECT :entity_id AS entity_id, :tag AS tag FROM DUAL) s
ON (t.ENTITY_ID = s.entity_id AND t.TAG = s.tag)
WHEN NOT MATCHED THEN INSERT (ENTITY_ID, TAG) VALUES (s.entity_id, s.tag);
```

此模式确保重复调用不会产生重复标签，实现API调用的幂等性。


---

## 6. 知识图谱

### 6.1 KNOWLEDGE_META结构

| 列名 | 类型 | 说明 |
|------|------|------|
| ENTITY_ID | VARCHAR2(64) | 知识实体ID（FK -> ENTITIES） |
| ENTITY_TYPE | VARCHAR2(20) | 默认KNOWLEDGE |
| DOMAIN | VARCHAR2(100) | 知识领域 |
| TOPIC | VARCHAR2(200) | 知识主题 |
| DIFFICULTY | VARCHAR2(20) | 难度等级（BEGINNER/INTERMEDIATE/ADVANCED/EXPERT） |
| VALIDATED_BY | VARCHAR2(100) | 验证者 |
| VALIDATION_STATUS | VARCHAR2(20) | 验证状态（PENDING/VALIDATED/REJECTED/CONTRADICTED） |
| REVIEW_COUNT | NUMBER | 复习次数 |
| NEXT_REVIEW_AT | TIMESTAMP | 下次复习时间 |

### 6.2 间隔复习机制

基于艾宾浩斯遗忘曲线实现间隔复习：

```sql
-- 复习间隔计算：LEAST(2^REVIEW_COUNT, 30) 天
NEXT_REVIEW_AT = CREATED_AT + NUMTODSINTERVAL(
    LEAST(POWER(2, REVIEW_COUNT), 30), 'DAY'
)
```

**复习间隔示例：**

| 复习次数 | 间隔天数 | 累计天数 |
|---------|---------|---------|
| 0 | 1 | 1 |
| 1 | 2 | 3 |
| 2 | 4 | 7 |
| 3 | 8 | 15 |
| 4 | 16 | 31 |
| 5 | 30(上限) | 61 |
| 6+ | 30(上限) | 每30天复习 |

艾宾浩斯遗忘曲线通过2的幂次复习间隔递增，保证知识在长期积累中不会遗忘。为避免间隔无限增长，设置30天上限，确保复习频率合理。

### 6.3 知识边关系

ENTITY_EDGES表定义5种知识边关系类型：

| 边类型 | 说明 | 属性 |
|------|------|------|
| DERIVES_FROM | 知识溯源（由...推导） | STRENGTH, CONFIDENCE |
| RELATES_TO | 相关知识 | STRENGTH, CONFIDENCE |
| CONTRADICTS | 知识矛盾（与...矛盾） | STRENGTH, CONFIDENCE |
| SUPPORTS | 知识支撑（支持...） | STRENGTH, CONFIDENCE |
| REQUIRES | 知识依赖（依赖...） | STRENGTH, CONFIDENCE |

每种边携带STRENGTH（关系强度，0-1）和CONFIDENCE（信心度，0-1）两个属性，用于衡量关系的可靠度与确定度。

### 6.4 矛盾检测与化解工作流

```
+------------+    +-------------+    +-------------+    +------------+
| CONTRADICTS|--->| 矛盾检测    |--->| 化解工作    |--->| 知识更新   |
| 边创建     |    | 自动标记    |    | 人工/自动   |    | 状态升级   |
+------------+    +-------------+    +-------------+    +------------+
                        |                   |
                        v                   v
                  VALIDATION_STATUS    1. 删除矛盾边
                  = CONTRADICTED       2. 更新VALIDATION_STATUS
                                       3. 创建SUPPORTS/DERIVES_FROM边
```

**矛盾化解工作流：**

1. **检测**：创建CONTRADICTS边时，自动标记矛盾知识的VALIDATION_STATUS为CONTRADICTED
2. **复解**：人工判定知识矛盾原因，删除矛盾边或更新知识状态
3. **更新**：矛盾知识验证状态为REJECTED，或创建新的SUPPORTS/DERIVES_FROM边强化知识关系

### 6.5 知识溯源

知识溯源通过DERIVES_FROM边实现上层/下层遍历：

```sql
-- 上层遍历：查找知识的所有上层溯源
SELECT CONNECT_BY_ROOT e.ENTITY_ID AS root_knowledge,
       e.ENTITY_ID AS ancestor,
       LEVEL AS depth
FROM ENTITY_EDGES e
WHERE e.EDGE_TYPE = 'DERIVES_FROM'
START WITH e.TARGET_ENTITY_ID = :knowledge_id
CONNECT BY PRIOR e.SOURCE_ENTITY_ID = e.TARGET_ENTITY_ID;

-- 下层遍历：查找知识派生的所有子知识
SELECT e.TARGET_ENTITY_ID AS descendant,
       LEVEL AS depth
FROM ENTITY_EDGES e
WHERE e.EDGE_TYPE = 'DERIVES_FROM'
START WITH e.SOURCE_ENTITY_ID = :knowledge_id
CONNECT BY PRIOR e.TARGET_ENTITY_ID = e.SOURCE_ENTITY_ID;
```

溯源遍历支持知识的完整溯源与推导路径追踪，确保知识可信度可追溯。


---

## 7. 规格驱动开发

### 7.1 概述

规格驱动开发（Specification-Driven Development, SDD）是v2.3.0的核心新特性，将规格说明提升为一等公民实体。规格作为ENTITIES的SPEC子类型，拥有完整的生命周期、元数据与计划关联机制，实现规格→计划→验证的完整闭环。

### 7.2 SPEC_META结构

| 列名 | 类型 | 说明 |
|------|------|------|
| ENTITY_ID | VARCHAR2(64) | 规格实体ID（FK -> ENTITIES） |
| ENTITY_TYPE | VARCHAR2(20) | 默认SPEC |
| SPEC_VERSION | VARCHAR2(20) | 规格版本号 |
| STATUS | VARCHAR2(20) | 规格状态 |
| SPEC_SCOPE | VARCHAR2(100) | 规格范围 |
| COMPLEXITY | VARCHAR2(20) | 复杂度等级 |
| ACCEPTANCE_CRITERIA | JSON | 验收标准（JSON数组） |
| CONSTRAINTS | JSON | 约束条件（JSON对象） |
| PARENT_SPEC_ID | VARCHAR2(64) | 父规格ID（用于规格派生） |

### 7.3 规格生命周期

```
+--------+     +----------+     +-----------+     +-------------+     +------------+
| DRAFT  |---->| PROPOSED |---->| ACCEPTED  |---->| IMPLEMENTED |---->| DEPRECATED |
| (草稿) |     | (提议)   |     | (已接受)  |     | (已实现)    |     | (已废弃)   |
+--------+     +----------+     +-----------+     +-------------+     +------------+
    |                |                |                  |                  |
    v                v                v                  v                  v
 创建规格      提交审查          审查通过          全部验收标准        新版本替代
 填写基本信息  完善验收标准      开始实现          通过验证            标记废弃
```

### 7.4 SPEC_PLAN_LINKS

规格与计划的多对多关联表：

| 列名 | 类型 | 说明 |
|------|------|------|
| SPEC_ID | VARCHAR2(64) | 规格ID |
| PLAN_ID | VARCHAR2(64) | 计划ID |
| LINK_TYPE | VARCHAR2(20) | 链接类型 |
| LINK_STRENGTH | NUMBER(3,2) | 链接强度 (0-1) |

**链接类型：**

| 类型 | 说明 |
|------|------|
| DRIVES | 规格驱动计划生成 |
| VALIDATES | 计划验证规格完成 |
| CONSTRAINS | 规格约束计划范围 |
| EXTENDS | 规格扩展计划能力 |

**唯一约束：** `(SPEC_ID, PLAN_ID, LINK_TYPE)` — 同一规格与同一计划的同一类型链接仅允许一条。

### 7.5 核心功能

**create_plan_from_spec：自动生成计划**

根据规格的验收标准（acceptance_criteria）自动生成TASK_PLAN及TASK_STEP：

```python
plan = create_plan_from_spec(spec_id="spec-001")
# 对于每个 acceptance criterion 自动创建一个 TASK_STEP
# 并创建 DRIVES 类型的 SPEC_PLAN_LINK
```

**validate_plan_against_spec：验证计划符合度**

检查计划步骤是否包含验收标准关键词，返回通过率：

```python
result = validate_plan_against_spec(spec_id="spec-001", plan_id="plan-001")
# 返回: {"pass_rate": 0.85, "matched": 6, "total": 7, "unmatched": ["并发安全检查"]}
```

**derive_spec：规格派生**

子规格继承父规格的元数据，自动递增版本号：

```python
child_spec = derive_spec(
    parent_spec_id="spec-001",
    title="增强版安全规格",
    additional_criteria=["支持双因素认证"],
    additional_constraints={"max_retry": 3}
)
# 版本号自动递增，创建 DERIVES_FROM 边
```

### 7.6 SPEC_MANAGER PL/SQL包

SPEC_MANAGER包含8个子程序：

| 子程序 | 类型 | 说明 |
|---------|------|------|
| create_spec | PROCEDURE | 创建规格实体及SPEC_META |
| update_spec_status | PROCEDURE | 更新规格状态 |
| link_spec_to_plan | PROCEDURE | 创建规格-计划链接 |
| get_spec_details | FUNCTION | 获取规格详情（含元数据） |
| get_specs_by_status | FUNCTION | 按状态查询规格 |
| validate_spec_plan | FUNCTION | 验证计划与规格的一致性 |
| derive_spec | PROCEDURE | 从父规格派生子规格 |
| get_spec_lineage | FUNCTION | 获取规格溯源链 |

### 7.7 spec_api.py

spec_api.py提供10个Python函数：

| 函数 | 参数 | 返回类型 |
|------|------|------|
| create_spec | title, content, scope, acceptance_criteria, constraints, importance, visibility, workspace_id | dict |
| get_spec | spec_id | dict |
| update_spec | spec_id, **kwargs | dict |
| update_spec_status | spec_id, new_status | dict |
| list_specs | status, scope, workspace_id | list |
| link_spec_to_plan | spec_id, plan_id, link_type, link_strength | dict |
| get_spec_plans | spec_id | list |
| create_plan_from_spec | spec_id, plan_title | dict |
| validate_plan_against_spec | spec_id, plan_id | dict |
| derive_spec | parent_spec_id, title, additional_criteria, additional_constraints | dict |

### 7.8 SPEC_DV：JRD可更新视图

SPEC_DV是规格实体的JRD Duality View，支持通过REST API直接对规格数据进行CRUD操作：

```sql
CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW SPEC_DV AS
SELECT d.ENTITY_ID, d.ENTITY_TYPE, d.TITLE, d.CONTENT,
       d.IMPORTANCE, d.VISIBILITY, d.WORKSPACE_ID,
       m.SPEC_VERSION, m.STATUS, m.SPEC_SCOPE, m.COMPLEXITY,
       m.ACCEPTANCE_CRITERIA, m.CONSTRAINTS, m.PARENT_SPEC_ID
FROM ENTITIES d
LEFT JOIN SPEC_META m ON d.ENTITY_ID = m.ENTITY_ID
WHERE d.ENTITY_TYPE = 'SPEC'
WITH INSERT UPDATE DELETE;
```


---

## 8. 智能体弹性管理

### 8.1 概述

v2.3.0引入两种新的智能体状态——DORMANT和POOL，配合凭证体系，实现智能体资源的弹性调度与高效利用。

### 8.2 新增智能体状态

| 状态 | 说明 | 特点 |
|------|------|------|
| **DORMANT** | 休眠状态 | 保留智能体身份、配置与历史记忆，临时停用以节约资源 |
| **POOL** | 池化状态 | 无状态空闲，上下文随用户走（通过凭证），按需匹配分配 |

**DORMANT vs POOL 对比：**


| 属性 | DORMANT | POOL |
|------|------|------|
| 身份保留 | 保留完整身份 | 无固定身份 |
| 上下文 | 保留在代理内 | 随凭证迁移 |
| 唤醒方式 | 直接唤醒 | 按技能匹配分配 |
| 资源占用 | 低（仅元数据） | 极低（仅注册信息） |
| 适用场景 | 季节性休眠 | 弹性会话池 |



### 8.3 AGENT_CREDENTIALS凭证体系

| 列名 | 类型 | 说明 |
|------|------|------|
| CREDENTIAL_ID | VARCHAR2(64) | 凭证唯一标识 |
| AGENT_ID | VARCHAR2(64) | 授权智能体 |
| USER_ID | VARCHAR2(100) | 授权用户 |
| SCOPE | JSON | 权限范围（如access_level, restricted_domains, max_clearance） |
| ENCRYPTED_TOKEN | VARCHAR2(512) | 加密凭证令牌（ReversibleEncryption） |
| IS_ACTIVE | VARCHAR2(1) | 是否有效 |
| ISSUED_AT | TIMESTAMP | 发行时间 |
| EXPIRES_AT | TIMESTAMP | 过期时间 |
| REVOKED_AT | TIMESTAMP | 撤销时间 |

**SCOPE JSON结构示侎：**

```json
{
    "access_level": "read_write",
    "restricted_domains": ["finance", "hr"],
    "max_clearance": 5
}
```

### 8.4 凭证生命周期

```
+--------+    +---------+    +-------+    +------------------+
| Issue  |--->| Verify  |--->|  Use  |--->| Revoke / Expiry  |
| (发行) |    | (验证)  |    | (使用)|    | (撤销/过期)      |
+--------+    +---------+    +-------+    +------------------+
     |             |             |                |
     v             v             v                v
 生成加密      解密验证       访问资源      IS_ACTIVE='N'
 写入数据库    SCOPE检查      日志审计      或硬删除
```

### 8.5 自动化作业

**DORMANT_AGENT_JOB：每30分钟执行**

自动将超过休眠超时时间的智能体转为DORMANT状态：

```sql
-- 读取 SYSTEM_CONFIG 中的 dormant_timeout_min 配置
-- 将超时的 ACTIVE 代理转为 DORMANT
UPDATE AGENTS SET STATUS = 'DORMANT'
WHERE STATUS = 'ACTIVE'
  AND UPDATED_AT < SYSTIMESTAMP - NUMTODSINTERVAL(
      (SELECT CONFIG_VALUE FROM SYSTEM_CONFIG WHERE CONFIG_KEY = 'dormant_timeout_min'),
      'MINUTE'
  );
```

**CREDENTIAL_CLEANUP_JOB：每日02:00执行**

两阶段清理过期凭证：

1. **软过期**：将已过期但未标记的凭证设置IS_ACTIVE='N'
2. **硬删除**：删除超过7天的已过期凭证记录

### 8.6 POOL代理匹配算法

POOL代理通过技能标签交集评分进行最佳匹配：

```python
def assign_pool_agent(required_skills: list, user_id: str) -> dict:
    # 1. 查找所有 POOL 状态的代理
    # 2. 计算 skills_tags 与 required_skills 的交集评分
    # 3. 选择评分最高的代理
    # 4. 发行凭证，转为 ACTIVE 状态
    # 5. 返回代理信息与凭证
```

### 8.7 agent_api.py新增函数

v2.3.0为agent_api.py新增8个函数：

| 函数 | 参数 | 返回类型 | 说明 |
|------|------|------|------|
| issue_credential | agent_id, user_id, scope, expires_hours | dict | 发行凭证 |
| verify_credential | credential_id | dict | 验证凭证 |
| get_credentials_for_user | user_id | list | 获取用户凭证 |
| revoke_credential | credential_id | dict | 撤销凭证 |
| hibernate_agent | agent_id | dict | 将代理转为DORMANT |
| wake_agent | agent_id | dict | 唤醒DORMANT代理 |
| register_pool_agent | name, skills_tags, description | dict | 注册POOL代理 |
| assign_pool_agent | required_skills, user_id | dict | 分配POOL代理 |

### 8.8 状态转换图

```
               +-----------+
               |  ACTIVE   |<---------+
               +-----------+          |
               /         |            |
          唤醒/          |休眠        |分配
             /           |            |
            v            v            |
      +---------+   +---------+   +-------+
      | DORMANT |   |DECOMMIS-|   | POOL  |
      | (休眠)  |   | SIONED  |   |(池化)|
      +---------+   |(已停用) |   +-------+
            |       +---------+       |
            |唤醒                     |匹配
            +-------> ACTIVE <--------+
```

**状态转换规则：**

- ACTIVE → DORMANT：超过dormant_timeout_min或手动休眠
- DORMANT → ACTIVE：手动唤醒
- POOL → ACTIVE：技能匹配分配（发行凭证）
- ACTIVE → DECOMMISSIONED：永久停用（不可逆）


---

## 9. 协作组

### 9.1 概述

协作组是v2.3.0引入的Mode C协作模式，支持组级共享工作空间与个人隔离工作空间的双层架构。每个协作组拥有一个共享工作空间，LEAD和CONTRIBUTOR还拥有各自的个人工作空间。

### 9.2 COLLAB_GROUPS结构

| 列名 | 类型 | 说明 |
|------|------|------|
| GROUP_ID | VARCHAR2(64) | 协作组ID |
| GROUP_NAME | VARCHAR2(200) | 组名称 |
| GROUP_TYPE | VARCHAR2(50) | 组类型 |
| WORKSPACE_ID | VARCHAR2(64) | 自动创建的共享工作空间ID |
| SHARING_POLICY | VARCHAR2(20) | 共享策略：OPEN/MODERATED/RESTRICTED |
| STATUS | VARCHAR2(20) | 组状态 |
| CREATED_BY | VARCHAR2(100) | 创建者 |
| CREATED_AT | TIMESTAMP | 创建时间 |

### 9.3 COLLAB_GROUP_MEMBERS结构

| 列名 | 类型 | 说明 |
|------|------|------|
| GROUP_ID | VARCHAR2(64) | 协作组ID |
| AGENT_ID | VARCHAR2(64) | 智能体ID |
| ROLE | VARCHAR2(20) | 角色：LEAD/CONTRIBUTOR/OBSERVER |
| PERSONAL_WORKSPACE_ID | VARCHAR2(64) | 个人工作空间ID（LEAD/CONTRIBUTOR专属） |
| JOINED_AT | TIMESTAMP | 加入时间 |

### 9.4 工作空间模型

```
+-----------------------------------------------------------+
|                  协作组工作空间模型                       |
|                                                           |
|  +-----------------------+  共享工作空间                  |
|  |  COLLAB_GROUP WS      |  TYPE=COLLAB_GROUP             |
|  |  ISOLATION=SHARED     |  所有成员可见                  |
|  +-----------------------+                                |
|                                                           |
|  +----------+ +----------+ +----------+  个人工作空间     |
|  |LEAD WS   | |CONTRIB WS| |LEAD WS   |  TYPE=PERSONAL_   |
|  |ISOLATED  | |ISOLATED  | |ISOLATED  |  IN_GROUP         |
|  +----------+ +----------+ +----------+  仅自己可见       |
|     LEAD      CONTRIBUTOR     LEAD                        |
+-----------------------------------------------------------+
```

**共享工作空间**：
- TYPE = COLLAB_GROUP
- ISOLATION = SHARED
- 所有成员均可访问共享记忆与知识

**个人工作空间**：
- TYPE = PERSONAL_IN_GROUP
- ISOLATION = ISOLATED
- 仅LEAD/CONTRIBUTOR可访问自己的个人空间
- OBSERVER无个人工作空间

### 9.5 共享策略

| 策略 | 说明 | 共享流程 |
|------|------|------|
| **OPEN** | 开放共享 | 任何成员可将记忆共享至组工作空间 |
| **MODERATED** | 审核共享 | LEAD/CONTRIBUTOR审批后方可共享 |
| **RESTRICTED** | 限制共享 | 仅LEAD可邀请或共享记忆 |

### 9.6 collab_api.py

collab_api.py提供10个Python函数：

| 函数 | 参数 | 返回类型 | 说明 |
|------|------|------|------|
| create_collab_group | group_name, group_type, sharing_policy, creator_agent_id | dict | 创建协作组 |
| get_collab_group | group_id | dict | 获取协作组信息 |
| update_collab_group | group_id, **kwargs | dict | 更新协作组 |
| add_group_member | group_id, agent_id, role | dict | 添加成员 |
| remove_group_member | group_id, agent_id | dict | 移除成员 |
| get_group_members | group_id | list | 获取成员列表 |
| share_memory_to_group | group_id, memory_id, from_workspace_id | dict | 共享记忆至组 |
| get_group_shared_memories | group_id | list | 获取组共享记忆 |
| list_collab_groups | agent_id | list | 列出代理所属组 |
| delete_collab_group | group_id | dict | 删除协作组 |

### 9.7 COLLAB_GROUP_MANAGER PL/SQL包

COLLAB_GROUP_MANAGER包含6个子程序：

| 子程序 | 类型 | 说明 |
|---------|------|------|
| create_group | PROCEDURE | 创建协作组及共享工作空间 |
| add_member | PROCEDURE | 添加成员及个人工作空间 |
| remove_member | PROCEDURE | 移除成员 |
| share_memory | PROCEDURE | 共享记忆到组工作空间 |
| get_group_info | FUNCTION | 获取组信息 |
| validate_access | FUNCTION | 验证成员访问权限 |

### 9.8 COLLAB_GROUP_DV：JRD可更新视图

```sql
CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW COLLAB_GROUP_DV AS
SELECT g.GROUP_ID, g.GROUP_NAME, g.GROUP_TYPE, g.SHARING_POLICY,
       g.STATUS, g.CREATED_BY, g.CREATED_AT,
       (SELECT JSON_ARRAYAGG(
           JSON_OBJECT(
               m.AGENT_ID, m.ROLE, m.PERSONAL_WORKSPACE_ID, m.JOINED_AT
           )
       ) FROM COLLAB_GROUP_MEMBERS m WHERE m.GROUP_ID = g.GROUP_ID) AS members
FROM COLLAB_GROUPS g
WITH INSERT UPDATE DELETE;
```


---

## 10. 工作空间与上下文连续性

### 10.1 WORKSPACES结构

| 列名 | 类型 | 说明 |
|------|------|------|
| WORKSPACE_ID | VARCHAR2(64) | 工作空间ID |
| NAME | VARCHAR2(200) | 工作空间名称 |
| TYPE | VARCHAR2(30) | 类型：CONVERSATION/PROJECT/TASK_CHAIN/AUTONOMOUS/COLLAB_GROUP/PERSONAL_IN_GROUP |
| ISOLATION | VARCHAR2(10) | 隔离模式：SHARED/ISOLATED |
| STATUS | VARCHAR2(20) | 状态：ACTIVE/PAUSED/ARCHIVED |
| DESCRIPTION | VARCHAR2(1000) | 描述 |
| CREATED_BY | VARCHAR2(100) | 创建者 |
| CREATED_AT | TIMESTAMP | 创建时间 |

**6种工作空间类型：**

| 类型 | 说明 | 隔离模式 |
|------|------|------|
| CONVERSATION | 对话型工作空间 | ISOLATED |
| PROJECT | 项目型工作空间 | SHARED |
| TASK_CHAIN | 任务链型工作空间 | ISOLATED |
| AUTONOMOUS | 自主型工作空间 | ISOLATED |
| COLLAB_GROUP | 协作组共享工作空间 | SHARED |
| PERSONAL_IN_GROUP | 组内个人工作空间 | ISOLATED |

**工作空间生命周期：**

```
+--------+    +--------+    +---------+
| ACTIVE |--->| PAUSED |--->| ARCHIVED|
| (活跃) |    | (暂停) |    | (归档)  |
+--------+    +--------+    +---------+
     |            |              |
     v            v              v
  正常使用     临时停止      仅读查询
```

### 10.2 WORKSPACE_CONTEXT结构

| 列名 | 类型 | 说明 |
|------|------|------|
| CONTEXT_ID | VARCHAR2(64) | 上下文ID |
| WORKSPACE_ID | VARCHAR2(64) | 所属工作空间 |
| SESSION_ID | VARCHAR2(64) | 关联会话 |
| CONTEXT_TYPE | VARCHAR2(30) | 上下文类型 |
| PARENT_CONTEXT_ID | VARCHAR2(64) | 父上下文（链式结构） |
| CONTENT_SNAPSHOT | CLOB | 上下文内容快照 |
| CREATED_AT | TIMESTAMP | 创建时间 |

**5种上下文类型：**

| 类型 | 说明 | JSON示侎 |
|------|------|------|
| CHECKPOINT | 工作检查点 | `{"progress": "60%", "state": "processing", "next_action": "validate"}` |
| HANDOFF | 代理交接 | `{"from_agent": "agent-A", "to_agent": "agent-B", "summary": "已完成分区配置"}` |
| SUMMARY | 阶段摘禁 | `{"key_decisions": ["选择引用分区"], "outstanding": ["测试验证"]}` |
| ERROR_STATE | 错误状态 | `{"error_code": "ORA-02270", "retry_count": 2, "last_error": "constraint violation"}` |
| AUTO_SAVE | 自动保存 | `{"unsaved_changes": true, "modified_entities": 5}` |

### 10.3 上下文链结构

```
+---------------+    +-----------+    +------------+    +-----------+
| CHECKPOINT    |--->|  HANDOFF  |--->|  SUMMARY   |--->|AUTO_SAVE  |
| (parent=NULL) |    |(parent=CK)|    | (parent=HO)|    |(parent=SM)|
+---------------+    +-----------+    +------------+    +-----------+
       |                   |                |                |
       v                   v                v                v
   初始状态           代理交接          阶段总结         自动保存
   进度信息           上下文传递        关键决策         未保存内容
```

上下文链采用追加式（Append-only）设计，每个新上下文通过PARENT_CONTEXT_ID链接至前一个上下文，形成不可变的时间序列。

### 10.4 代理交接机制

```
+----------+  PREDECESSOR   +----------+  OWNER_USER   +----------+
| Session A|--------------->| Session B|-------------->| Session C|
| agent-A  |  SESSION_ID    | agent-B  | WORKSPACE_ID  | agent-C  |
+----------+                +----------+               +----------+
     |                           |                          |
     v                           v                          v
  创建HANDOFF                继承上下文                 继承上下文
  上下文                    工作空间+WORKSPACE_ID       工作空间
```

**AGENT_SESSION关键字段：**

- PREDECESSOR_SESSION_ID：前驱会话，链接会话序列
- OWNER_USER_ID：会话所属用户
- WORKSPACE_ID：会话工作空间

### 10.5 核心函数

**create_handoff_session：创建交接会话**

```python
new_session = create_handoff_session(
    predecessor_session_id="sess-A",
    agent_id="agent-B",
    workspace_id="ws-001"
)
# 自动创建 HANDOFF 上下文
# 设置 PREDECESSOR_SESSION_ID 链接
```

**recover_workspace：恢复工作空间**

```python
context = recover_workspace(workspace_id="ws-001")
# 加载最新上下文
# 获取会话链
# 返回: {"context": ..., "session_chain": [...], "latest_context": ...}
```

### 10.6 workspace_api.py

workspace_api.py提供14个Python函数：

| 函数 | 参数 | 返回类型 |
|------|------|------|
| create_workspace | name, ws_type, isolation, description, created_by | dict |
| get_workspace | workspace_id | dict |
| update_workspace | workspace_id, **kwargs | dict |
| list_workspaces | ws_type, status | list |
| archive_workspace | workspace_id | dict |
| add_context | workspace_id, session_id, context_type, content_snapshot, parent_context_id | dict |
| get_context_chain | workspace_id | list |
| get_latest_context | workspace_id | dict |
| create_handoff_session | predecessor_session_id, agent_id, workspace_id | dict |
| recover_workspace | workspace_id | dict |
| pause_workspace | workspace_id | dict |
| resume_workspace | workspace_id | dict |
| get_workspace_entities | workspace_id, entity_type | list |
| search_workspace_contexts | workspace_id, context_type | list |


---

## 11. 任务规划引擎

### 11.1 TASK_PLANS结构

TASK_PLANS采用LIST分区（按STATUS）+RANGE分区（按CREATED_AT），支持ROW MOVEMENT：

| 列名 | 类型 | 说明 |
|------|------|------|
| PLAN_ID | VARCHAR2(64) | 计划ID |
| STATUS | VARCHAR2(20) | 计划状态（LIST分区键） |
| TITLE | VARCHAR2(500) | 计划标题 |
| DESCRIPTION | CLOB | 计划描述 |
| CREATED_BY | VARCHAR2(100) | 创建者 |
| CREATED_AT | TIMESTAMP | 创建时间（RANGE分区键） |

**复合主键：** `(PLAN_ID, STATUS)` — 支持引用分区的子表TASK_STEPS

**分区策略：**

- LIST分区：按STATUS分区（PLANNED/IN_PROGRESS/COMPLETED/FAILED/CANCELLED）
- RANGE分区：按CREATED_AT时间范围分区
- ROW MOVEMENT：状态变更时自动将行迁移至目标分区

### 11.2 TASK_STEPS结构

TASK_STEPS从TASK_PLANS引用分区，复合主键`(STEP_ID, PLAN_ID, PLAN_STATUS)`：

| 列名 | 类型 | 说明 |
|------|------|------|
| STEP_ID | VARCHAR2(64) | 步骤ID |
| PLAN_ID | VARCHAR2(64) | 计划ID |
| PLAN_STATUS | VARCHAR2(20) | 计划状态（引用分区键） |
| STEP_NUMBER | NUMBER | 步骤编号 |
| STEP_TITLE | VARCHAR2(500) | 步骤标题 |
| STEP_DESCRIPTION | CLOB | 步骤描述 |
| STEP_STATUS | VARCHAR2(20) | 步骤状态 |
| TOOL_INPUT | JSON | 工具调用输入（JSON） |
| TOOL_OUTPUT | JSON | 工具调用输出（JSON） |
| ASSIGNED_AGENT | VARCHAR2(64) | 执行智能体 |

### 11.3 TASK_CONTEXT_SNAPSHOTS

| 列名 | 类型 | 说明 |
|------|------|------|
| SNAPSHOT_ID | VARCHAR2(64) | 快照ID |
| PLAN_ID | VARCHAR2(64) | 计划ID |
| STEP_ID | VARCHAR2(64) | 步骤ID（执行点） |
| CONTEXT_TYPE | VARCHAR2(20) | 快照类型（breakpoint/recovery） |
| CONTEXT_DATA | JSON | 快照数据 |
| CREATED_AT | TIMESTAMP | 创建时间 |

### 11.4 TASK_TOOL_CALLS

| 列名 | 类型 | 说明 |
|------|------|------|
| CALL_ID | VARCHAR2(64) | 调用ID |
| STEP_ID | VARCHAR2(64) | 步骤ID |
| TOOL_NAME | VARCHAR2(100) | 工具名称 |
| INPUT_DATA | JSON | 调用输入 |
| OUTPUT_DATA | JSON | 调用输出 |
| START_TIME | TIMESTAMP | 开始时间 |
| END_TIME | TIMESTAMP | 结束时间 |
| DURATION_MS | NUMBER | 调用时长（毫秒） |

### 11.5 TASK_DEPENDENCIES

| 列名 | 类型 | 说明 |
|------|------|------|
| DEPENDENCY_ID | VARCHAR2(64) | 依赖关系ID |
| SOURCE_STEP_ID | VARCHAR2(64) | 依赖源步骤 |
| TARGET_STEP_ID | VARCHAR2(64) | 依赖目标步骤 |
| DEPENDENCY_TYPE | VARCHAR2(20) | 依赖类型 |
| CREATED_AT | TIMESTAMP | 创建时间 |

**4种依赖类型：**

| 类型 | 说明 |
|------|------|
| BLOCKS | 阻塞依赖（阻止目标步骤开启） |
| ENABLES | 使能依赖（允许目标步骤开启） |
| RELATES_TO | 相关依赖（建议性，不阻塞） |
| CONFLICTS | 冲突依赖（禁止目标步骤开启） |

### 11.6 task_plan_api.py

task_plan_api.py提供6个Python函数：

| 函数 | 参数 | 返回类型 |
|------|------|------|
| create_task_plan | title, description, steps, created_by | dict |
| get_task_plan | plan_id | dict |
| update_step_status | step_id, new_status, tool_output | dict |
| add_task_dependency | source_step_id, target_step_id, dependency_type | dict |
| get_plan_steps | plan_id | list |
| create_context_snapshot | plan_id, step_id, context_type, context_data | dict |

---

## 12. Harness模板系统

### 12.1 概述

Harness模板是ENTITIES的HARNESS_TEMPLATE子类型，提供智能体行为规范的定义模板。包含提示模板、工具绑定、记忆访问配置、护栏与评估规则。

### 12.2 HARNESS_META结构

| 列名 | 类型 | 说明 |
|------|------|------|
| ENTITY_ID | VARCHAR2(64) | 模板实体ID |
| ENTITY_TYPE | VARCHAR2(20) | 默认HARNESS_TEMPLATE |
| TEMPLATE_VERSION | VARCHAR2(20) | 模板版本 |
| STATUS | VARCHAR2(20) | 生命周期状态：DRAFT/PUBLISHED/DEPRECATED |
| PROMPT_TEMPLATES | JSON | 提示模板集合 |
| TOOL_BINDINGS | JSON | 工具绑定配置 |
| MEMORY_ACCESS | JSON | 记忆访问配置 |
| GUARDRAILS | JSON | 护栏规则 |
| EVALUATION | JSON | 评估规则 |

### 12.3 模板生命周期

```
+--------+    +-----------+    +------------+
| DRAFT  |--->| PUBLISHED |--->| DEPRECATED |
| (草稿) |    | (已发行)  |    | (已废弃)   |
+--------+    +-----------+    +------------+
     |              |                |
     v              v                v
  创建与编译    使用于智能体     新版本替代
```

### 12.4 模板继承

模板可通过DERIVES_FROM边实现继承，子模板继承父模板的全部组件，并可追加或覆盖特定配置：

```python
child_template = derive_harness_template(
    parent_id="ht-research",
    name="安全研究模板",
    additional_guardrails={"no_external_api": True},
    modified_prompt_templates={"analysis": "专注安全护栏的研究提示"}
)
```

### 12.5 5个内置模板

| 模板名称 | 说明 | 关键组件 |
|---------|------|----------|
| Research Analyst | 研究分析智能体 | deep_search提示, 信息检索工具绑定 |
| Code Assistant | 编程助理智能体 | code_generation提示, 代码工具绑定 |
| Data Analyst | 数据分析智能体 | sql_generation提示, 数据工具绑定 |
| Task Planner | 任务规划智能体 | planning提示, 任务执行工具绑定 |
| Security Auditor | 安全审计智能体 | security_check提示, 安全工具绑定 |

### 12.6 harness_api.py

harness_api.py提供6个Python函数：

| 函数 | 参数 | 返回类型 |
|------|------|------|
| create_harness_template | name, prompt_templates, tool_bindings, memory_access, guardrails, evaluation | dict |
| get_harness_template | template_id | dict |
| update_harness_template | template_id, **kwargs** | dict |
| publish_harness_template | template_id | dict |
| deprecate_harness_template | template_id | dict |
| derive_harness_template | parent_id, name, **kwargs** | dict |


---

## 13. 属性图API

### 13.1 概述

本系统基于Oracle 26ai属性图（Property Graph）构建实体关系网络，使用GRAPH_TABLE SQL运算符实现图查询。单一属性图ORACLE_MEMORY_GRAPH以ENTITIES为顶点、ENTITY_EDGES为边。

### 13.2 ORACLE_MEMORY_GRAPH定义

```sql
CREATE OR REPLACE PROPERTY GRAPH ORACLE_MEMORY_GRAPH
    VERTEX TABLES (
        ENTITIES
            KEY (ENTITY_ID, ENTITY_TYPE)
            PROPERTIES (ENTITY_ID, ENTITY_TYPE, TITLE, IMPORTANCE, VISIBILITY, WORKSPACE_ID)
            LABEL ENTITIES
    )
    EDGE TABLES (
        ENTITY_EDGES
            KEY (EDGE_ID)
            SOURCE KEY (SOURCE_ENTITY_ID) REFERENCES ENTITIES (ENTITY_ID)
            DESTINATION KEY (TARGET_ENTITY_ID) REFERENCES ENTITIES (ENTITY_ID)
            PROPERTIES (EDGE_TYPE, STRENGTH, CONFIDENCE)
            LABEL EDGES
    );
```

### 13.3 graph_api.py

graph_api.py提供9个Python函数，均使用GRAPH_TABLE SQL运算符：

| 函数 | 参数 | 返回类型 | 说明 |
|------|------|------|------|
| create_entity_graph | entity_id, target_id, edge_type, strength, confidence | dict | 创建实体关系边 |
| shortest_path | from_id, to_id | list | 查找两实体间最短路径 |
| get_neighbors | entity_id, edge_type, direction, depth | list | 获取邻居节点 |
| get_community | entity_id, max_depth | list | 获取社区检测 |
| graph_stats | - | dict | 图统计信息 |
| search_by_structure | pattern, min_strength | list | 按结构模式搜索 |
| get_entity_timeline | entity_id | list | 获取实体时间线 |
| get_strongest_path | from_id, to_id | list | 查找最强关系路径 |
| export_graph | entity_ids, depth | dict | 导出子图 |

### 13.4 GRAPH_TABLE查询示侎

**最短路径查找：**

```sql
SELECT *
FROM GRAPH_TABLE (ORACLE_MEMORY_GRAPH
    MATCH (a)-[e]->{1,10}(b)
    WHERE a.ENTITY_ID = :from_id AND b.ENTITY_ID = :to_id
    COLUMNS (a.ENTITY_ID AS from_id, b.ENTITY_ID AS to_id,
             LISTAGG(e.EDGE_TYPE, ',') AS path_types,
             COUNT(e) AS hop_count)
)
ORDER BY hop_count
FETCH FIRST 1 ROW ONLY;
```

**社区检测：**

```sql
SELECT b.ENTITY_ID, b.TITLE, COUNT(*) AS connection_count
FROM GRAPH_TABLE (ORACLE_MEMORY_GRAPH
    MATCH (a)-[e]->{1,3}(b)
    WHERE a.ENTITY_ID = :entity_id
    COLUMNS (b.ENTITY_ID, b.TITLE)
)
GROUP BY b.ENTITY_ID, b.TITLE
ORDER BY connection_count DESC;
```

### 13.5 典型使用场景

| 场景 | 说明 | 使用函数 |
|------|------|------|
| 知识遍历 | 沿关系边遍历知识网络 | get_neighbors, shortest_path |
| 相似度搜索 | 查找结构相似的实体 | search_by_structure |
| 社区检测 | 识别知识社区 | get_community |
| 路径查找 | 发现实体间的隐含关系 | shortest_path, get_strongest_path |


---

## 14. 五信号融合检索

### 14.1 概述

v2.3.1引入五信号融合检索（5-Signal Unified Search），这是系统检索能力的核心升级。传统向量检索仅依赖语义相似度，无法捕捉结构化属性、文本精确匹配、标签关联和图关系等多维信息。五信号融合通过加权组合五种独立评分信号，实现全面的多维度检索排序。

五信号融合检索的设计哲学是**让每种数据模态为检索贡献其独特价值**：向量信号捕捉语义相似性，全文信号捕捉精确词法匹配，关系型信号利用结构化元数据过滤，标签信号补充分类信息，图信号挖掘实体间关系邻近度。五种信号各自归一化到[0,1]区间后加权求和，权重可按业务场景灵活调整。

### 14.2 五信号体系

| 信号 | 默认权重 | 数据源 | 评分算法 |
|------|---------|--------|----------|
| **Vector** | 0.40 | ENTITY_EMBEDDINGS | 1 - VECTOR_DISTANCE(COSINE) |
| **Fulltext** | 0.25 | Oracle Text CONTAINS | SCORE(1) / 100 |
| **Relational** | 0.20 | KNOWLEDGE_META + SPEC_META + ENTITIES | 属性匹配评分 + importance归一化 |
| **Tag** | (含在relational) | ENTITY_TAGS | 标签交集比例 + 查询词匹配 |
| **Graph** | 0.15 | ENTITY_EDGES BFS | 1/depth递减 + edge_count/10加成 |

**信号详细说明：**

- **Vector信号**：调用外部embedding API（text-embedding-bge-m3，1024维）将查询文本向量化，通过`VECTOR_DISTANCE(COSINE)`计算与ENTITY_EMBEDDINGS中向量的余弦相似度。这是语义层面的核心信号，能捕捉"数据库分区"与"表分割策略"之间的语义关联，即便词汇完全不匹配
- **Fulltext信号**：基于Oracle Text CONTEXT索引（ENTITIES_SEARCH_CTX），使用`CONTAINS(e.TITLE, :ftq, 1) > 0`和`SCORE(1)`计算全文相关性。支持布尔运算（AND/OR/NOT）、模糊匹配（$word）、词干扩展。与向量信号互补：向量擅长语义匹配，全文擅长精确词法匹配
- **Relational信号**：利用KNOWLEDGE_META（domain/topic/difficulty）、SPEC_META（scope/complexity/status）和ENTITIES（category/importance）的结构化元数据。当查询指定domain="database"时，domain匹配的实体获得额外加分。importance评分归一化为`importance/10`
- **Tag信号**：计算ENTITY_TAGS与过滤标签的交集比例，以及查询词与标签文本的匹配度。标签与relational信号合计权重0.2，避免信号碎片化
- **Graph信号**：基于种子实体在ENTITY_EDGES上的BFS遍历（非GRAPH_TABLE，因复合PK匹配问题），邻近度按`1/depth`递减。连接度加成为`edge_count/10`。例如，与种子实体直接相邻(depth=1)的实体获得1.0邻近度，间接相邻(depth=2)获得0.5

### 14.3 融合算法

```
+----------+  +----------+  +-------------------+  +----------+
| Vector   |  | Fulltext |  | Relational + Tag  |  |  Graph   |
| Score    |  | Score    |  | Score             |  | Score    |
| [0, 1]   |  | [0, 1]   |  | [0, 1]            |  | [0, 1]   |
+----+-----+  +----+-----+  +-----+-------------+  +----+-----+
     |             |              |                     |
     v             v              v                     v
  x 0.40        x 0.25         x 0.20                 x 0.15
     |             |              |                     |
     +-------------+--------------+---------------------+
                                  |
                                  v
                          加权求和 final_score
                       （降序返回 top_k 结果）
```

**融合公式：**

```
final_score = 0.40 × vec + 0.25 × ft + 0.20 × (rel + tag) + 0.15 × graph
```

权重可自定义：`search_unified(text, vector_weight=0.3, fulltext_weight=0.3, relational_weight=0.2, graph_weight=0.2)`

**单SQL融合检索：** `search_unified_sql()` 提供与 `search_unified` 完全相同的五信号融合，但通过单条CTE SQL语句完成，消除多轮Python-SQL往返：

```sql
WITH candidates AS (...向量+全文主查询...),
     tag_scores AS (...标签GROUP BY评分...),
     edge_counts AS (...边计数GROUP BY...),
     graph_prox AS (...图邻近UNION ALL depth=1+2...)
SELECT ... 加权评分 ... ORDER BY final_score DESC
```

**单SQL融合检索的核心优势：**

| 优势维度 | 多步检索（search_unified） | 单SQL融合（search_unified_sql） |
|---------|------------------------|---------------------------|
| 数据库往返 | 4-5次（向量→标签→图→边数→合并） | **1次**（CTE链+最终SELECT） |
| Token开销 | 每步调用产生请求/响应token，5步≈500-1000 token工具调用开销 | **1次调用≈100-200 token**，节省60-80% |
| 上下文占用 | 中间步骤结果（标签列表、边计数、图邻近映射）暂存于Python内存，间接占用LLM上下文 | **服务端完成全部计算**，仅返回最终排序结果 |
| 上下文污染风险 | 中间过程的调试日志、部分匹配、空结果等噪音可能泄漏至LLM上下文 | **零中间步骤**，消除噪音来源 |
| 延迟 | 4-5次网络往返，总延迟=各步之和 | **单次往返**，延迟约等于最长子查询 |

对LLM智能体而言，单SQL融合检索的真正价值不仅是性能提升，更是**上下文经济学**：每一次工具调用都有token成本，每一步中间结果都有污染风险。将5次调用压缩为1次，意味着智能体可以用更少的上下文开销获取更高质量的检索结果，将宝贵的token预算留给推理与决策。

### 14.4 search_unified API

```python
results = search_unified(
    text="database partitioning strategies",
    top_k=20,
    entity_type="KNOWLEDGE",
    domain="database",
    tags=["partitioning", "oracle"],
    graph_seed_entity_id="abc123",
    vector_weight=0.4,
    fulltext_weight=0.25,
    relational_weight=0.2,
    graph_weight=0.15,
)

for r in results:
    print(f"{r['title']:40s} final={r['final_score']:.3f}")
    print(f"  vec={r['scores']['vector']:.3f} ft={r['scores']['fulltext']:.3f} "
          f"rel={r['scores']['relational']:.3f} tag={r['scores']['tag']:.3f} "
          f"graph={r['scores']['graph']:.3f}")
```

### 14.5 返回字段

每条结果包含完整的五信号评分明细：

| 字段 | 类型 | 说明 |
|------|------|------|
| entity_id | str | 实体ID |
| entity_type | str | 实体类型 |
| title | str | 实体标题 |
| category | str | 分类 |
| importance | int | 重要性评分 |
| km_domain | str | 知识领域（如有） |
| km_topic | str | 知识主题（如有） |
| sm_scope | str | 规格范围（如有） |
| tags | list | 标签列表 |
| edge_count | int | 关系边数 |
| graph_proximity | float | 图邻近度 |
| scores.vector | float | 向量信号评分 [0,1] |
| scores.fulltext | float | 全文信号评分 [0,1] |
| scores.relational | float | 关系型信号评分 [0,1] |
| scores.tag | float | 标签信号评分 [0,1] |
| scores.graph | float | 图信号评分 [0,1] |
| final_score | float | 加权最终评分 |

---

## 15. 全文搜索引擎

### 15.1 概述

v2.3.1集成Oracle Text全文搜索引擎，通过CONTEXT索引实现对ENTITIES表TITLE和CONTENT列的高性能全文检索。与向量检索的语义匹配不同，全文检索擅长精确词法匹配——当用户搜索"partitioning"时，包含该词的实体将被精确命中并按相关性评分排序。

Oracle Text全文搜索是五信号融合检索中fulltext信号的底层引擎。它也可独立使用，适用于已知确切关键词、需要布尔组合或模糊匹配的检索场景。

### 15.2 CONTEXT索引架构

```sql
-- 创建多列数据存储偏好
BEGIN
    CTX_DDL.CREATE_PREFERENCE('ENTITIES_MCD', 'MULTI_COLUMN_DATASTORE');
    CTX_DDL.SET_ATTRIBUTE('ENTITIES_MCD', 'COLUMNS', 'TITLE, CONTENT');
END;
/

-- 创建CONTEXT索引，SYNC ON COMMIT保证实时性
CREATE INDEX ENTITIES_SEARCH_CTX ON ENTITIES(TITLE)
INDEXTYPE IS CTXSYS.CONTEXT
PARAMETERS ('DATASTORE ENTITIES_MCD SYNC (ON COMMIT)');
```

**架构设计说明：**

- **MULTI_COLUMN_DATASTORE**：将TITLE和CONTENT两列合并为一个虚拟文档供Oracle Text索引，搜索时同时匹配标题和内容
- **SYNC (ON COMMIT)**：每次事务提交后自动同步索引，确保新写入的数据立即可搜索
- **CONTEXT索引类型**：适合大文本CLOB列的全文检索，非实时索引（区别于JSON_CONTEXT）

### 15.3 查询语法

Oracle Text支持丰富的查询语法：

| 语法 | 示例 | 说明 |
|------|------|------|
| 确词 | `partitioning` | 匹配包含"partitioning"的文档 |
| 布尔AND | `database AND partitioning` | 同时包含两个词 |
| 布尔OR | `encryption OR security` | 包含任一词 |
| 布尔NOT | `database NOT mongodb` | 包含前者但排除后者 |
| 模糊匹配 | `$partitioning` | 容忍拼写错误的模糊匹配 |
| 词干扩展 | `$run` | 匹配running/ran/runs等词干变体 |
| 短语搜索 | `"exact phrase"` | 精确短语匹配 |

### 15.4 search_fulltext API

```python
# 基础全文搜索
results = search_fulltext("partitioning", top_k=10)
for r in results:
    print(f"{r['title']:40s} ft_score={r['ft_score']:.3f}")

# 带过滤的全文搜索
results = search_fulltext(
    query="encryption AND credential",
    entity_type="KNOWLEDGE",
    category="security",
    top_k=5,
)

# 布尔组合搜索
results = search_fulltext("database NOT mongodb", top_k=10)
```

---

## 16. 统一搜索API

### 16.1 概述

search_api.py提供10种搜索策略的统一入口，是AI智能体调用检索能力的首选接口。智能体可根据场景需要显式选择策略，也可使用`strategy="auto"`让系统自动检测最优策略。

统一搜索API的设计目标是**简化AI智能体的检索调用**：无需记忆多个模块的不同函数签名，只需一个`search()`函数即可覆盖从关键词匹配到五信号融合的全部检索场景。

**LLM上下文经济学设计理念：**

统一搜索API的深层设计动机是**降低检索对LLM上下文的占用与污染**。传统做法下，AI智能体获取"与安全加密相关的记忆、知识和规格"需要：调用`search_memories`获取记忆列表、调用`search_knowledge`获取知识列表、调用`search_similar`获取向量相似结果——3次工具调用，3组请求/响应，数百token开销，且中间结果可能包含大量无关噪音。

统一搜索API将此压缩为**一次调用**：

```python
# 传统方式：3次调用，≈600 token工具开销，3组中间结果污染上下文
memories = search_memories(keyword="encryption")
knowledge = search_knowledge(keyword="encryption")
similar = search_similar(text="encryption")

# 统一搜索API：1次调用，≈120 token，无中间噪音
results = search("encryption", strategy="unified", top_k=10)
```

一次调用返回的`results`列表已按五信号综合评分排序，智能体无需自行合并、去重、排序多组结果，直接进入推理与决策阶段。这意味着：

- **Token节省**：从N次工具调用压缩到1次，减少60-80%的工具调用token开销
- **上下文纯净**：无中间步骤噪音，LLM上下文保持"检索结果→推理决策"的清晰链路
- **决策效率**：预排序的融合结果让智能体更快定位最相关信息，减少在多组结果间反复比较的推理token消耗

### 16.2 10种策略一览

| 策略 | 信号模态 | 最佳场景 | 需要Embedding |
|------|---------|---------|--------------|
| **vector** | 向量相似度 | 语义/概念搜索 | 是 |
| **fulltext** | 全文相关性 | 确关键词/布尔/模糊 | 否 |
| **keyword** | SQL LIKE | 通配符/部分匹配 | 否 |
| **graph** | 图关系 | 邻居探索/路径查找 | 否 |
| **hybrid** | 向量+全文 | 语义+词汇平衡 | 是 |
| **unified** | 五信号融合 | 综合多维检索 | 是 |
| **unified_sql** | 五信号融合(单SQL) | 低延迟生产检索 | 是 |
| **relational** | 结构化属性 | 域/分类/难度筛选 | 否 |
| **multi_type** | 跨类型向量 | MEMORY/KNOWLEDGE/SPEC联合 | 是 |
| **auto** | 自动检测 | 未知类型/便捷入口 | 视情况 |

### 16.3 自动策略检测规则

当strategy="auto"时，系统根据查询特征自动选择最优策略：

| 规则 | 检测条件 | 选择策略 |
|------|---------|---------|
| 布尔表达式 | 含 AND/OR/NOT | fulltext |
| 模糊/词干 | 含 $ 或 ~ | fulltext |
| 通配符 | 含 % 或 _ | keyword |
| 过滤条件 | 指定 domain/tags | unified |
| 图种子 | 指定 graph_seed_entity_id | unified |
| 短查询 | ≤2 词 | fulltext |
| 长查询 | ≥5 词 | unified |
| 默认 | 其他 | hybrid |

### 16.4 核心函数

**search() — 统一搜索入口**

```python
from scripts.lib.search_api import search, list_search_strategies, describe_search_strategy

# 自动策略检测
results = search("database partitioning", strategy="auto", top_k=10)
print(f"策略: {results['strategy']}, 结果数: {results['count']}")

# 显式策略选择
results = search("encryption", strategy="fulltext", entity_type="KNOWLEDGE", top_k=5)
results = search("partition%", strategy="keyword", top_k=10)
results = search("architecture", strategy="vector", top_k=5)
results = search("security", strategy="unified", domain="security", top_k=10)
```

返回结构：`{"strategy": "...", "query": "...", "results": [...], "count": N}`

**list_search_strategies() — 策略列表**

```python
strats = list_search_strategies()
for s in strats:
    print(f"{s['strategy']:12s} {s['name']}  signals={s['signals']}")
```

**describe_search_strategy() — 策略详情**

```python
desc = describe_search_strategy("unified")
print(f"参数列表: {desc['parameters']}")
```

### 16.5 策略选择建议

**典型场景与推荐策略：**

| 场景 | 推荐策略 | 原因 |
|------|---------|------|
| AI智能体一般检索 | auto | 自动匹配，最便捷 |
| 生产低延迟检索 | unified_sql | 单SQL五信号融合，最小往返延迟 |
| 精确关键词查找 | fulltext | 全文相关性评分最高 |
| 语义相似内容发现 | vector | 纯语义匹配 |
| 带过滤条件的深度检索 | unified | 五信号融合+多维过滤 |
| 查找相关实体关系 | graph | 图邻居遍历 |
| 跨类型内容关联 | multi_type | MEMORY/KNOWLEDGE/SPEC联合 |
| 简单通配符搜索 | keyword | LIKE模式匹配 |
| 结构化属性筛选 | relational | domain/category/importance过滤 |
| 语义+词汇双需求 | hybrid | 向量+全文平衡 |



---

## 17. 安全体系

### 23.1 DataMaskingService

数据脱敏服务支持7种敏感模式的上下文感知脱敏：

| 模式 | 正则表达式 | 脱敏规则 | 示侎 |
|------|----------|----------|------|
| credit_card | \d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4} | 仅保留后4位 | ****-****-****-1234 |
| ssn | \d{3}-\d{2}-\d{4} | 仅保留后4位 | ***-**-5678 |
| jwt_token | eyJ[A-Za-z0-9-_]+\.eyJ[A-Za-z0-9-_]+ | 完全脱敏 | [REDACTED_JWT] |
| api_key | [A-Za-z0-9]{32,} | 仅保留前4位 | sk-1***[REDACTED] |
| email | [\w.+-]+@[\w-]+\.[\w.]+ | 遮掩用户名 | j***@example.com |
| ip_address | \d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3} | 遮掩后2段 | 10.10.***.*** |
| phone | \d{3}[-.]?\d{3}[-.]?\d{4} | 仅保留后4位 | ***-***-5678 |

**上下文感知脱敏：** 根据数据周围的键名（如"password"、"secret"）自动增强脱敏级别，即使值未匹配已知模式也会进行脱敏。

### 23.2 ReversibleEncryption

基于AES的可逆加密，用于凭证存储：

```python
class ReversibleEncryption:
    def __init__(self):
        # 从 SYSTEM_CONFIG 加载自动生成的密钥
        self.key = self._load_encryption_key()

    def encrypt(self, plaintext: str) -> str:
        # AES 加密，返回 Base64 编码的密文
        ...

    def decrypt(self, ciphertext: str) -> str:
        # AES 解密，返回明文
        ...
```

**密钥管理：** 密钥自动生成并存储在SYSTEM_CONFIG表中，仅有特权账户可访问。

### 23.3 密码哈希

```python
def hash_password(password: str) -> str:
    # SHA256 哈希，带前缀
    return "SHA256:" + hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, password_hash: str) -> bool:
    # 比较哈希值
    return hash_password(password) == password_hash
```

### 23.4 可见性访问控制

基于VISIBILITY字段的三级访问控制：

```python
def check_entity_access(entity, user_id, workspace_id):
    if entity['VISIBILITY'] == 'PUBLIC':
        return True
    elif entity['VISIBILITY'] == 'SHARED':
        return entity['WORKSPACE_ID'] == workspace_id
    elif entity['VISIBILITY'] == 'PRIVATE':
        return entity['CREATED_BY'] == user_id
    return False
```

### 23.5 AGENT_PERMISSION_MANAGER

AGENT_PERMISSION_MANAGER PL/SQL包提供三个核心子程序：

| 子程序 | 说明 |
|---------|------|
| check_entity_access | 检查实体访问权限 |
| check_workspace_access | 检查工作空间访问权限 |
| log_access | 记录访问日志 |

### 23.6 会话安全

| 参数 | 值 | 说明 |
|------|------|------|
| 会话超时 | 300分钟 | 默认会话超时时间 |
| 密码验证 | SHA256 | 哈希比较，非明文存储 |
| 认证方式 | Session-based | 基于会话的身份认证 |


---

## 18. 企业级数据架构

### 21.1 分区策略全览

本系统采用精心设计的分区策略，11张分区表各有其分区逻辑：

| 表名 | 分区类型 | 分区键 | 说明 |
|------|----------|----------|------|
| ENTITIES | LIST | ENTITY_TYPE | 按实体类型分区 |
| MEMORY_META | REFERENCE | (FK) | 引用分区，自动继承 |
| KNOWLEDGE_META | REFERENCE | (FK) | 引用分区，自动继承 |
| SPEC_META | REFERENCE | (FK) | 引用分区，自动继承 |
| HARNESS_META | REFERENCE | (FK) | 引用分区，自动继承 |
| TAGS | REFERENCE | (FK) | 引用分区，自动继承 |
| ENTITY_EDGES | REFERENCE | (FK) | 引用分区，自动继承 |
| TASK_PLANS | LIST+RANGE | STATUS, CREATED_AT | 复合分区，支持ROW MOVEMENT |
| TASK_STEPS | REFERENCE | (FK) | 引用分区，自动继承 |
| AGENTS | HASH | AGENT_ID | 按代理ID哈希分区 |
| AGENT_SESSIONS | HASH | SESSION_ID | 按会话ID哈希分区 |

### 21.2 复合主键设计

| 表名 | 复合主键 | 目的 |
|------|----------|------|
| ENTITIES | (ENTITY_ID, ENTITY_TYPE) | 支持引用分区 |
| MEMORY_META | (ENTITY_ID, ENTITY_TYPE) | 匹配父表复合PK |
| KNOWLEDGE_META | (ENTITY_ID, ENTITY_TYPE) | 匹配父表复合PK |
| TASK_PLANS | (PLAN_ID, STATUS) | 支持引用分区+ROW MOVEMENT |
| TASK_STEPS | (STEP_ID, PLAN_ID, PLAN_STATUS) | 匹配父表复合PK |

### 21.3 JRD Duality Views清单

| 视图名 | 模式 | 根表 | 嵌套对象 |
|------|------|------|----------|
| ENTITIES_DV | INSERT/UPDATE/DELETE | ENTITIES | MEMORY_META, KNOWLEDGE_META |
| AGENTS_DV | INSERT/UPDATE/DELETE | AGENTS | AGENT_SESSIONS, AGENT_CREDENTIALS |
| TASK_PLANS_DV | INSERT/UPDATE/DELETE | TASK_PLANS | TASK_STEPS |
| WORKSPACES_DV | INSERT/UPDATE/DELETE | WORKSPACES | WORKSPACE_CONTEXT |
| SPEC_DV | INSERT/UPDATE/DELETE | ENTITIES(SPEC) | SPEC_META, SPEC_PLAN_LINKS |
| COLLAB_GROUP_DV | INSERT/UPDATE/DELETE | COLLAB_GROUPS | COLLAB_GROUP_MEMBERS |

### 21.4 索引策略

系统共创40+索引，主要包括：

- **主键索引**：所有复合PK自动创建唯一索引
- **外键索引**：所有FK列自动创建索引，加速JOIN查询
- **业务查询索引**：如ENTITIES表的(ENTITY_TYPE, VISIBILITY, WORKSPACE_ID)、(ENTITY_TYPE, IMPORTANCE)等
- **时间范围索引**：CREATED_AT、NEXT_REVIEW_AT等时间字段
- **JSON索引**：对ENTITY_DATA中的高频查询字段创建多值索引

### 21.5 ID生成策略

所有VARCHAR2(64)类型的ID均使用RAWTOHEX(SYS_GUID())生成，确保全局唯一性：

```sql
ENTITY_ID RAWTOHEX(SYS_GUID())  -- 生成32位十六进制字符串
```

### 21.6 JSON策略

| 操作 | 方法 | 说明 |
|------|------|------|
| 写入 | json.dumps() | Python端序列化 |
| 读取 | 自动转dict | oracledb自动反序列化 |
| 更新 | JSON_TRANSFORM | 逐字段更新，非JSON_MERGEPATCH |
| 存储 | OSON | Oracle原生二进制JSON格式 |


---

## 19. 自动化运维

### 22.1 11个调度作业

| 作业名 | 调度 | 说明 |
|---------|--------|------|
| MEMORY_FUSION_JOB | 每6小时 | 融合相似记忆，提取高重要性知识 |
| MEMORY_DECAY_JOB | 每日 03:00 | 记忆衰弒（x0.95因子） |
| KNOWLEDGE_REVIEW_JOB | 每日 04:00 | 检查并标记待复习知识 |
| KNOWLEDGE_EXTRACTION_JOB | 每日 05:00 | 从记忆自动提取知识 |
| DORMANT_AGENT_JOB | 每30分钟 | 自动休眠超时的智能体 |
| CREDENTIAL_CLEANUP_JOB | 每日 02:00 | 两阶段清理过期凭证 |
| EMBEDDING_GENERATION_JOB | 每2小时 | 自动生成缺失的embedding向量 |
| SESSION_CLEANUP_JOB | 每日 01:00 | 清理过期会话 |
| WORKSPACE_ARCHIVE_JOB | 每周日 06:00 | 归档不活跃工作空间 |
| CONSTRAINTS_CHECK_JOB | 每日 00:00 | 检查数据一致性约束 |
| STATISTICS_UPDATE_JOB | 每日 22:00 | 更新表统计信息 |
| INDEX_REBUILD_JOB | 每周日 03:00 | 重建碎片化索引 |

### 22.2 作业设计模式

**幂等部署**：所有作业均使用MERGE INTO或条件检查，确保重复执行不会产生副作用。

**SYSTEM_CONFIG配置驱动**：关键参数（如dormant_timeout_min、decay_factor）存储在SYSTEM_CONFIG表中，作业运行时动态读取，无需重新编译。

**两阶段清理**：CREDENTIAL_CLEANUP_JOB采用软过期（IS_ACTIVE='N'）+硬删除的两阶段模式，避免误删有效凭证。

**内联PL/SQL**：复杂业务逻辑使用内联PL/SQL块，减少对外部存储过程的依赖。

### 22.3 DORMANT_AGENT_JOB详解

```sql
BEGIN
    -- 读取 SYSTEM_CONFIG 中的 dormant_timeout_min
    DECLARE
        v_timeout NUMBER;
    BEGIN
        SELECT CONFIG_VALUE INTO v_timeout
        FROM SYSTEM_CONFIG
        WHERE CONFIG_KEY = 'dormant_timeout_min';

        -- 将超时的 ACTIVE 代理转为 DORMANT
        UPDATE AGENTS
        SET STATUS = 'DORMANT', UPDATED_AT = SYSTIMESTAMP
        WHERE STATUS = 'ACTIVE'
          AND UPDATED_AT < SYSTIMESTAMP - NUMTODSINTERVAL(v_timeout, 'MINUTE');

        -- 记录日志
        INSERT INTO SYSTEM_LOGS (LOG_ID, LOG_LEVEL, MESSAGE, CREATED_AT)
        VALUES (RAWTOHEX(SYS_GUID()), 'INFO',
                'DORMANT_AGENT_JOB: ' || SQL%ROWCOUNT || ' agents hibernated',
                SYSTIMESTAMP);
    END;
END;
```

### 22.4 CREDENTIAL_CLEANUP_JOB详解

```sql
BEGIN
    -- 第一阶段：软过期 - 将已过期的凭证标记为不活跃
    UPDATE AGENT_CREDENTIALS
    SET IS_ACTIVE = 'N', REVOKED_AT = SYSTIMESTAMP
    WHERE IS_ACTIVE = 'Y'
      AND EXPIRES_AT < SYSTIMESTAMP;

    -- 第二阶段：硬删除 - 删除超过7天的已过期凭证
    DELETE FROM AGENT_CREDENTIALS
    WHERE IS_ACTIVE = 'N'
      AND REVOKED_AT < SYSTIMESTAMP - 7;
END;
```


---

## 20. 可视化控制台

### 23.1 8页面仪表盘

| 页面 | 路由 | 功能 |
|------|------|------|
| Knowledge | /knowledge | 知识管理与浏览 |
| Memory | /memory | 记忆管理与搜索 |
| Agents | /agents | 智能体管理与监控 |
| Tasks | /tasks | 任务规划与进度 |
| Workspaces | /workspaces | 工作空间管理 |
| Graph Explorer | /graph | 属性图可视化探索 |
| Specs | /specs | 规格管理与验证 |
| Collab | /collab | 协作组管理 |

### 23.2 技术架构

**模板化架构：**

```
+-------------------+
|    server.py      |  主服务器，路由分发
+-------------------+
        |
        +--> templates/          9 HTML模板文件
        +--> static/style.css    暗色主题样式
        +--> static/vis-network.min.js  图可视化库
```

**暗色主题与CSS变量：**

```css
:root {
    --bg-primary: #1a1a2e;
    --bg-secondary: #16213e;
    --bg-card: #0f3460;
    --text-primary: #e6e6e6;
    --text-secondary: #a8a8a8;
    --accent: #e94560;
    --success: #4ecca3;
    --warning: #ffd369;
    --danger: #ff6b6b;
}
```

### 23.3 双语界面

采用data-zh/data-en属性实现中英双语界面：

```html
<span data-zh="记忆管理" data-en="Memory Management">记忆管理</span>
```

- 语言偏好存储在localStorage
- 切换语言时动态更新所有标签
- 支持中英文两种界面语言

### 23.4 安全特性

| 特性 | 说明 |
|------|------|
| 5分钟自动登出 | 带倒计时器，超时自动返回登录页 |
| Session认证 | 基于SHA256密码验证的会话认证 |
| 登录页 | 统一的身份认证入口 |

### 23.5 API端点

| 端点 | 方法 | 说明 |
|------|------|------|
| /api/knowledge | GET | 获取知识列表 |
| /api/memory | GET | 获取记忆列表 |
| /api/agents | GET | 获取代理列表 |
| /api/tasks | GET | 获取任务列表 |
| /api/workspaces | GET | 获取工作空间列表 |
| /api/specs | GET | 获取规格列表 |
| /api/collab | GET | 获取协作组列表 |
| /api/stats | GET | 获取系统统计 |
| /api/graph/neighbors | GET | 获取图邻居节点 |
| /api/graph/context | GET | 获取图上下文 |
| /api/graph/stats | GET | 获取图统计 |
| /api/graph/search | GET | 图搜索 |
| /api/graph/all | GET | 获取全图数据 |

### 23.6 详情展示

| 视图 | 展示方式 |
|------|----------|
| 列表视图 | 内联行展开（inline row expansion） |
| 图视图 | 右侧面板展示（带关闭按钮） |


---

## 21. API参考

### 21.1 connection.py (4函数)

| 函数 | 参数 | 返回类型 |
|------|------|------|
| get_connection | - | oracledb.Connection |
| close_connection | connection | None |
| execute_query | sql, params, connection | list[dict] |
| execute_dml | sql, params, connection | int |

### 21.2 memory_api.py (8函数)

| 函数 | 参数 | 返回类型 |
|------|------|------|
| create_memory | title, content, category, importance, visibility, workspace_id, created_by, tags | dict |
| get_memory | memory_id | dict |
| update_memory | memory_id, **kwargs | dict |
| delete_memory | memory_id | dict |
| search_memories | keyword, category, visibility, workspace_id, importance_min, limit | list |
| reinforce_memory | memory_id | dict |
| get_memories_by_workspace | workspace_id, limit | list |
| get_memory_tags | memory_id | list |

### 21.3 knowledge_api.py (7函数)

| 函数 | 参数 | 返回类型 |
|------|------|------|
| create_knowledge | title, content, domain, topic, difficulty, importance, visibility, workspace_id, created_by, validated_by | dict |
| get_knowledge | knowledge_id | dict |
| update_knowledge | knowledge_id, **kwargs | dict |
| delete_knowledge | knowledge_id | dict |
| search_knowledge | keyword, domain, topic, difficulty, validation_status, limit | list |
| add_knowledge_edge | source_id, target_id, edge_type, strength, confidence | dict |
| get_knowledge_edges | knowledge_id, edge_type | list |

### 21.4 agent_api.py (17函数)

| 函数 | 参数 | 返回类型 |
|------|------|------|
| create_agent | name, agent_type, description, skills_tags, config | dict |
| get_agent | agent_id | dict |
| update_agent | agent_id, **kwargs | dict |
| delete_agent | agent_id | dict |
| list_agents | status, agent_type | list |
| create_session | agent_id, user_id, workspace_id | dict |
| get_session | session_id | dict |
| update_session | session_id, **kwargs | dict |
| end_session | session_id | dict |
| get_agent_sessions | agent_id, limit | list |
| get_sessions_by_user | user_id | list |
| issue_credential | agent_id, user_id, scope, expires_hours | dict |
| verify_credential | credential_id | dict |
| get_credentials_for_user | user_id | list |
| revoke_credential | credential_id | dict |
| hibernate_agent | agent_id | dict |
| wake_agent | agent_id | dict |
| register_pool_agent | name, skills_tags, description | dict |
| assign_pool_agent | required_skills, user_id | dict |

### 21.5 task_plan_api.py (6函数)

| 函数 | 参数 | 返回类型 |
|------|------|------|
| create_task_plan | title, description, steps, created_by | dict |
| get_task_plan | plan_id | dict |
| update_step_status | step_id, new_status, tool_output | dict |
| add_task_dependency | source_step_id, target_step_id, dependency_type | dict |
| get_plan_steps | plan_id | list |
| create_context_snapshot | plan_id, step_id, context_type, context_data | dict |

### 21.6 harness_api.py (6函数)

| 函数 | 参数 | 返回类型 |
|------|------|------|
| create_harness_template | name, prompt_templates, tool_bindings, memory_access, guardrails, evaluation | dict |
| get_harness_template | template_id | dict |
| update_harness_template | template_id, **kwargs** | dict |
| publish_harness_template | template_id | dict |
| deprecate_harness_template | template_id | dict |
| derive_harness_template | parent_id, name, **kwargs** | dict |

### 21.7 graph_api.py (9函数)

| 函数 | 参数 | 返回类型 |
|------|------|------|
| create_entity_graph | entity_id, target_id, edge_type, strength, confidence | dict |
| shortest_path | from_id, to_id | list |
| get_neighbors | entity_id, edge_type, direction, depth | list |
| get_community | entity_id, max_depth | list |
| graph_stats | - | dict |
| search_by_structure | pattern, min_strength | list |
| get_entity_timeline | entity_id | list |
| get_strongest_path | from_id, to_id | list |
| export_graph | entity_ids, depth | dict |

### 21.8 workspace_api.py (14函数)

| 函数 | 参数 | 返回类型 |
|------|------|------|
| create_workspace | name, ws_type, isolation, description, created_by | dict |
| get_workspace | workspace_id | dict |
| update_workspace | workspace_id, **kwargs | dict |
| list_workspaces | ws_type, status | list |
| archive_workspace | workspace_id | dict |
| add_context | workspace_id, session_id, context_type, content_snapshot, parent_context_id | dict |
| get_context_chain | workspace_id | list |
| get_latest_context | workspace_id | dict |
| create_handoff_session | predecessor_session_id, agent_id, workspace_id | dict |
| recover_workspace | workspace_id | dict |
| pause_workspace | workspace_id | dict |
| resume_workspace | workspace_id | dict |
| get_workspace_entities | workspace_id, entity_type | list |
| search_workspace_contexts | workspace_id, context_type | list |

### 21.9 spec_api.py (10函数)

| 函数 | 参数 | 返回类型 |
|------|------|------|
| create_spec | title, content, scope, acceptance_criteria, constraints, importance, visibility, workspace_id | dict |
| get_spec | spec_id | dict |
| update_spec | spec_id, **kwargs | dict |
| update_spec_status | spec_id, new_status | dict |
| list_specs | status, scope, workspace_id | list |
| link_spec_to_plan | spec_id, plan_id, link_type, link_strength | dict |
| get_spec_plans | spec_id | list |
| create_plan_from_spec | spec_id, plan_title | dict |
| validate_plan_against_spec | spec_id, plan_id | dict |
| derive_spec | parent_spec_id, title, additional_criteria, additional_constraints | dict |

### 21.10 collab_api.py (10函数)

| 函数 | 参数 | 返回类型 |
|------|------|------|
| create_collab_group | group_name, group_type, sharing_policy, creator_agent_id | dict |
| get_collab_group | group_id | dict |
| update_collab_group | group_id, **kwargs | dict |
| add_group_member | group_id, agent_id, role | dict |
| remove_group_member | group_id, agent_id | dict |
| get_group_members | group_id | list |
| share_memory_to_group | group_id, memory_id, from_workspace_id | dict |
| get_group_shared_memories | group_id | list |
| list_collab_groups | agent_id | list |
| delete_collab_group | group_id | dict |

### 21.11 security.py (4函数)

| 函数 | 参数 | 返回类型 |
|------|------|------|
| mask_sensitive_data | text | str |
| encrypt_value | plaintext | str |
| decrypt_value | ciphertext | str |
| verify_password | password, password_hash | bool |


---

## 22. 部署与运维

### 22.1 部署流程

三阶段部署，按顺序执行：

```
+----------------+    +------------+    +-----------+    +---------------------+
| 1_schema.sql   |--->| 2_api.sql  |--->| 3_jobs.sql|--->| 4_harness_templates |
| 创建表、分区、 |    | 创建PL/SQL |    | 创建调度  |    | 创建内置模板        |
| 索引、视图     |    | 包、视图   |    | 作业      |    | (可选)              |
+----------------+    +------------+    +-----------+    +---------------------+
```

### 22.2 前置条件

| 组件 | 版本要求 |
|------|----------|
| Oracle Database | 23ai+（推荐26ai） |
| Python | 3.8+（推荐3.14.5） |
| oracledb | 4.0.0+ |
| SQLcl | 26.1+ |

### 22.3 配置方式

支持两种配置方式：

**环境变量：**

```bash
export DB_HOST=<your_db_host>
export DB_PORT=1521
export DB_SERVICE=<your_service_name>
export DB_USER=memory_user
export DB_PASSWORD=<your_password>
export WEB_PORT=8000
```

**config.json：**

```json
{
    "db_host": "<your_db_host>",
    "db_port": 1521,
    "db_service": "<your_service_name>",
    "db_user": "memory_user",
    "db_password": "<your_password>",
    "web_port": 8000,
    "session_timeout": 300
}
```

### 22.4 测试执行

```bash
cd scripts && python -m tests.test_all
```

测试结果：183/183通过，100%通过率（14套测试，含Embedding 19项 + 统一搜索 20项 + 搜索API 36项）。

### 22.5 服务器控制

```bash
# 启动
./start_web_server.sh start

# 停止
./start_web_server.sh stop

# 重启
./start_web_server.sh restart

# 状态
./start_web_server.sh status
```

### 22.6 从 v2.2.x 升级

v2.3.0向下兼容，升级操作：

```sql
-- 添加新分区
ALTER TABLE ENTITIES ADD PARTITION VALUES ('SPEC');

-- 添加新列
ALTER TABLE ENTITIES ADD COLUMN ENTITY_DATA JSON;
ALTER TABLE MEMORY_META ADD COLUMN CATEGORY VARCHAR2(100);

-- 创建新表
@1_schema.sql  -- 仅执行新增部分

-- 更新PL/SQL包
@2_api.sql
```

### 22.7 已知问题与解决方案

| 问题 | 解决方案 |
|------|----------|
| CONSTRAINTS保留字 | 使用双引号\"CONSTRAINTS\"包裹 |
| ORA-01745命名绑定 | 避免使用Oracle保留字作为绑定变量名 |
| JSON_OBJECT FORMAT JSON | 使用JSON_OBJECT(*)替代手动FORMAT JSON |
| JSON_MERGEPATCH OSON错误 | 使用JSON_TRANSFORM替代JSON_MERGEPATCH |
| 引用分区DISABLE约束 | 引用分区子表不支持DISABLE约束，初始化时先ENABLE |
| JSON_QUERY双层方括号 | WITH WRAPPER返回[[...]]，用SUBSTR去外层再TO_VECTOR |
| VECTOR列ORA-01722 | oracledb thin mode位置绑定对VECTOR列报错，必须使用命名绑定 |
| TO_VECTOR格式 | Oracle 23ai要求[v1,v2,...]方括号格式，不接受纯逗号分隔 |


---

## 23. 版本演进

### 23.1 版本历史

| 版本 | 日期 | 核心特性 |
|------|------|----------|
| **v2.3.1** | 2026-05-26 | 向量检索修复、五信号融合检索、全文搜索引擎、统一搜索API（9策略） |
| **v2.3.0** | 2026-05-24 | 规格驱动开发（SDD）、弹性智能体管理（DORMANT/POOL）、协作组 |
| **v2.2.1** | 2026-05-23 | 模板可视化、侧边栏导航、Graph Explorer |
| **v2.2.0** | 2026-05-20 | 工作空间与上下文连续性、JRD Duality Views |
| **v2.1.0** | 2026-05-19 | 表分区、复合主键、属性图 |
| **v2.0.0** | 2026-05-15 | 统一架构重写、oracledb驱动 |
| **v1.x** | 2026-04-05 | 初始版本发布 |

### 23.2 各版本详解

**v2.3.1 (2026-05-26) — 向量检索 + 五信号融合 + 全文搜索 + 统一搜索API**

- 修复EMBEDDING_MANAGER PL/SQL包（JSON_QUERY双层方括号问题）
- 新增embedding_api.py（14函数），全部命名绑定修复ORA-01722
- 新增EMBEDDING_GENERATION_JOB（每2小时自动生成embedding）
- 新增search_unified()五信号融合检索（vector+fulltext+relational+tag+graph）
- 新增Oracle Text CONTEXT索引ENTITIES_SEARCH_CTX
- 新增search_fulltext()全文搜索
- 新增search_api.py统一搜索入口（10种策略+自动检测）
- 新增19+20+36=75项测试，总计183项全部通过

**v2.3.0 (2026-05-24) — 规格驱动 + 弹性管理 + 协作**

- 新增SPEC实体类型与SPEC_META表
- 新增SPEC_PLAN_LINKS规格-计划关联表
- 新增SPEC_MANAGER PL/SQL包（8子程序）
- 新增spec_api.py（10函数）和SPEC_DV视图
- 新增DORMANT/POOL智能体状态
- 新增AGENT_CREDENTIALS凭证表
- 新增DORMANT_AGENT_JOB和CREDENTIAL_CLEANUP_JOB
- 新增agent_api.py +8函数
- 新增COLLAB_GROUPS和COLLAB_GROUP_MEMBERS表
- 新增collab_api.py（10函数）和COLLAB_GROUP_MANAGER包
- 新增COLLAB_GROUP_DV视图

**v2.2.1 (2026-05-23) — 可视化增强**

- Harness模板可视化管理页面
- 侧边栏导航优化
- Graph Explorer交互式图探索

**v2.2.0 (2026-05-20) — 工作空间与上下文**

- 工作空间与上下文连续性系统
- 代理交接机制
- JRD Duality Views（6个视图）

**v2.1.0 (2026-05-19) — 企业级分区**

- 全表分区策略
- 复合主键设计
- 属性图支持

**v2.0.0 (2026-05-15) — 架构重写**

- 统一实体模型重写
- 迁移至oracledb驱动
- Python API层重构

**v1.x (2026-04-05) — 初始版本**

- 基础记忆存储
- 简单知识管理
- 基本代理管理


---

## 24. 术语表

| 术语 | 英文 | 定义 |
|------|--------|------|
| ENTITIES | Entities | 统一实体表，存储7种类型的实体数据 |
| JRD | JSON Relational Duality | Oracle 26ai的JSON关系二元性视图，支持通过REST API对关系数据进行CRUD |
| SDD | Specification-Driven Development | 规格驱动开发，将规格说明作为一等公民实体驱动开发流程 |
| DORMANT | Dormant State | 智能体休眠状态，保留身份与配置，临时停用以节约资源 |
| POOL | Pool State | 智能体池化状态，无状态空闲，按需技能匹配分配 |
| 引用分区 | Reference Partitioning | Oracle分区特性，子表通过外键自动继承父表分区策略 |
| GRAPH_TABLE | Graph Table Operator | Oracle SQL图查询运算符，在SQL中查询属性图 |
| OSON | Oracle JSON Binary | Oracle原生二进制JSON存储格式，高性能读写 |
| ReversibleEncryption | Reversible Encryption | 基于AES的可逆加密，用于凭证令牌存储 |
| 间隔复习 | Spaced Review | 基于艾宾浩斯遗忘曲线的知识复习机制，复习间隔随复习次数指数递增 |
| 复合主键 | Composite Primary Key | 由多个列组成的主键，支持引用分区 |
| 记忆融合 | Memory Fusion | 相似记忆的自动合并与知识提取过程 |
| 记忆衰减 | Memory Decay | 记忆重要性随时间指数衰减的机制 |
| 工作空间 | Workspace | 隔离的工作环境，包含实体、上下文与会话 |
| 上下文链 | Context Chain | 追加式上下文序列，支持代理交接与恢复 |
| 属性图 | Property Graph | Oracle 26ai原生图数据结构，支持顶点和边的属性 |
| 规格 | Specification (SPEC) | 系统行为规范的正式定义，作为ENTITIES的SPEC子类型 |
| 五信号融合检索 | 5-Signal Unified Search | vector+fulltext+relational+tag+graph五信号加权融合检索 |
| 全文搜索引擎 | Oracle Text Fulltext Search | 基于Oracle Text CONTEXT索引的全文检索引擎 |
| 统一搜索API | Unified Search API | 10种搜索策略的统一入口，支持自动策略检测 |
| CONTEXT索引 | Oracle Text CONTEXT Index | Oracle Text全文索引类型，支持大文本CLOB列检索 |
| Embedding | Vector Embedding | 文本的向量嵌入表示，用于语义相似度计算 |
| BFS图邻近性 | BFS Graph Proximity | 基于广度优先搜索的图邻近度评分，1/depth递减 |
| 协作组 | Collaboration Group | 多智能体协作的组织形式，包含共享与个人工作空间 |
| 凭证体系 | Credential System | 基于加密凭证的智能体访问授权机制 |
| ROW MOVEMENT | Row Movement | Oracle分区特性，允许行在分区间迁移 |
| 单表多态 | Single-Table Polymorphism | 将多种类型实体存储在同一张表中的设计模式 |

---

*本白皮书由尹海文编写，Oracle AI 数据库记忆系统 v2.3.1，2026年5月发布，Apache 2.0许可证。*
