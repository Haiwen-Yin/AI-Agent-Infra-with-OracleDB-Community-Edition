# Oracle AI 数据库记忆系统 v2.3.0

**版本**: v2.3.0 | **日期**: 2026-05-24 | **作者**: 尹海文 | **许可**: Apache License 2.0

> v2.3.0 是重大功能版本，新增规格驱动开发（SDD）、智能体弹性管理、协作组三大子系统，与 v2.2.x 数据库向后兼容。

---

## 一、v2.3.0 更新内容

### 1. 规格驱动开发（Spec Driven Development, SDD）

将规格（Specification）提升为一等公民，存储为 ENTITIES 的 `SPEC` 子类型，实现规格与计划的正式关联：

| 组件 | 说明 |
|------|------|
| SPEC_META 表 | 从 ENTITIES 引用分区；存储版本、状态、验收标准、约束条件 |
| SPEC_PLAN_LINKS 表 | 规格↔计划多对多关系；LINK_TYPE: DRIVES/VALIDATES/CONSTRAINS/EXTENDS |
| SPEC_DV 视图 | JRD 可更新双重视图，支持规格的文档API操作 |
| SPEC_MANAGER 包 | 8个PL/SQL子程序：创建、查询、更新、验证、派生、从规格创建计划、关联规格与计划 |
| spec_api.py | 10个Python函数，覆盖SDD完整生命周期 |

**规格生命周期**: DRAFT → PROPOSED → ACCEPTED → IMPLEMENTED → DEPRECATED

### 2. 智能体弹性管理（Agent Elastic Management）

新增两种智能体状态，实现资源优化和凭据认证：

| 状态 | 说明 | 上下文 | 适用场景 |
|------|------|--------|----------|
| DORMANT（休眠） | 临时休眠，保留身份 | 保留（智能体身份+会话数据不变） | 智能体暂停、成本优化 |
| POOL（池化） | 无状态空闲 | 通过凭据跟随用户 | 按需智能体分配 |

**凭据系统**: AGENT_CREDENTIALS 表采用可逆加密存储凭据，自动过期，SCOPE JSON定义权限范围。

**POOL 智能体匹配**: 根据智能体的 `skills_tags` 与用户需求的交集匹配，选择最佳匹配的池化智能体分配。

**新增 agent_api.py 函数（8个）**: issue_credential, verify_credential, get_credentials_for_user, revoke_credential, hibernate_agent, wake_agent, register_pool_agent, assign_pool_agent

### 3. 协作组（Collaboration Groups）

Mode C 协作模型，支持组级共享工作区和个人工作区：

| 组件 | 说明 |
|------|------|
| COLLAB_GROUPS 表 | 组定义：GROUP_TYPE、SHARING_POLICY（OPEN/MODERATED/RESTRICTED）、STATUS |
| COLLAB_GROUP_MEMBERS 表 | 成员资格：ROLE（LEAD/CONTRIBUTOR/OBSERVER） |
| COLLAB_GROUP_DV 视图 | JRD 可更新双重视图 |
| COLLAB_GROUP_MANAGER 包 | 6个PL/SQL子程序 |
| collab_api.py | 10个Python函数 |

**工作区模型**: 每个协作组自动创建一个共享工作区（TYPE=COLLAB_GROUP）。LEAD 和 CONTRIBUTOR 成员额外获得个人工作区（TYPE=PERSONAL_IN_GROUP）。OBSERVER 不获得个人工作区。

---

## 二、架构概览

```
ENTITIES（按 ENTITY_TYPE LIST 分区）
  +----------+----------+----------+--------+----------+-----+
  | MEMORY   | KNOWLEDGE|TASK_OUT  |EXPERI- | HARNESS_ |SPEC |
  | 记忆     | 知识     |PUT       |ENCE    | TEMPLATE |规格 |
  +----------+----------+----------+--------+----------+-----+
  6个引用分区子表: EDGES, KNOWLEDGE_META, SPEC_META[新],
                   HARNESS_META, EMBEDDINGS, TAGS

27张表 | 6个JRD视图 | 7个PL/SQL包 | 11个调度作业
12个Python模块 | 99+ API函数 | 99/99 测试通过
```

---

## 三、数据库架构（27张表）

| 分类 | 表名 | 说明 |
|------|------|------|
| **核心** | ENTITIES | 统一实体存储（7种类型） |
| | ENTITY_EDGES | 有向关系边，引用分区 |
| | KNOWLEDGE_META | 知识元数据，引用分区 |
| | SPEC_META [新] | 规格元数据，引用分区 |
| | HARNESS_META | Harness模板元数据，引用分区 |
| | ENTITY_EMBEDDINGS | 向量嵌入，引用分区 |
| | ENTITY_TAGS | 标签，引用分区 |
| **系统** | SYSTEM_USERS | 用户账户（SHA256密码哈希） |
| | SYSTEM_CONFIG | 键值配置存储 |
| | TAGS | 标签定义 |
| **智能体** | AGENT_REGISTRY | 智能体定义+弹性管理（+5新列） |
| | AGENT_CREDENTIALS [新] | 加密凭据存储 |
| | AGENT_SESSION | 会话+交接链 |
| | ENTITY_ACCESS_LOG | 实体访问审计 |
| | AGENT_PERMISSION_LOG | 权限变更审计 |
| **协作** | AGENT_COLLABORATION | 智能体间协作记录 |
| | COLLAB_GROUPS [新] | 协作组定义 |
| | COLLAB_GROUP_MEMBERS [新] | 组成员 |
| **工作区** | WORKSPACES | 工作区生命周期（6种类型） |
| | WORKSPACE_CONTEXT | 上下文链（追加写入） |
| | WORKSPACE_TASKS | 工作区↔任务计划关联 |
| **任务** | TASK_PLANS | 任务计划（LIST+RANGE分区） |
| | TASK_STEPS | 计划步骤（引用分区） |
| | TASK_CONTEXT_SNAPSHOTS | 步骤执行上下文 |
| | TASK_TOOL_CALLS | 工具调用记录 |
| | TASK_DEPENDENCIES | 步骤依赖图 |
| **规格** | SPEC_PLAN_LINKS [新] | 规格↔计划多对多 |

---

## 四、分区策略

| 表 | 分区方式 |
|----|----------|
| ENTITIES | LIST(ENTITY_TYPE) — 7个分区 |
| ENTITY_EDGES / KNOWLEDGE_META / SPEC_META / HARNESS_META / ENTITY_EMBEDDINGS / ENTITY_TAGS | 引用分区（继承ENTITIES） |
| AGENT_SESSION | LIST(IS_ACTIVE) + RANGE(START_TIME) |
| ENTITY_ACCESS_LOG | RANGE(ACCESS_TIME) + HASH(AGENT_ID) |
| TASK_PLANS | LIST(STATUS) + RANGE(CREATED_AT) |
| TASK_STEPS | 引用分区（继承TASK_PLANS） |

---

## 五、JRD 双重视图（6个）

| 视图 | 模式 | 根表 | 嵌套对象 |
|------|------|------|----------|
| WORKSPACE_DV | 可更新 | WORKSPACES | WORKSPACE_TASKS |
| CONTEXT_DV | 只读 | WORKSPACE_CONTEXT | — |
| MEMORY_DV | 可更新 | ENTITIES(MEMORY) | ENTITY_TAGS, ENTITY_EDGES |
| KNOWLEDGE_DV | 可更新 | ENTITIES(KNOWLEDGE) | ENTITY_TAGS, ENTITY_EDGES |
| SPEC_DV [新] | 可更新 | ENTITIES(SPEC) | SPEC_META, SPEC_PLAN_LINKS |
| COLLAB_GROUP_DV [新] | 可更新 | COLLAB_GROUPS | COLLAB_GROUP_MEMBERS |

---

## 六、PL/SQL 包（7个）

| 包名 | 子程序数 | 说明 |
|------|---------|------|
| MEMORY_FUSION_ENGINE | 7 | 记忆融合 |
| KNOWLEDGE_BASE_API | 5 | 知识管理 |
| AGENT_PERMISSION_MANAGER | 5 | 权限管理 |
| SESSION_CLEANUP | 4 | 会话清理 |
| WORKSPACE_MANAGER | 10 | 工作区管理 |
| SPEC_MANAGER [新] | 8 | 规格管理 |
| COLLAB_GROUP_MANAGER [新] | 6 | 协作组管理 |

---

## 七、调度作业（11个）

| 作业 | 调度 | 说明 |
|------|------|------|
| MEMORY_FUSION_JOB | 每日 03:00 | 融合相似记忆 |
| MEMORY_FUSION_CYCLE | 每日 04:00 | 完整融合周期 |
| MEMORY_FUSION_STATS | 每日 05:00 | 融合统计 |
| SESSION_CLEANUP_JOB | 每小时 | 清理过期会话 |
| SESSION_EXPIRY_NOTIFICATION | 每小时 | 会话到期通知 |
| KNOWLEDGE_EXTRACTION_JOB | 每日 06:00 | 知识提取 |
| KNOWLEDGE_GRAPH_MAINTENANCE | 每周日 01:00 | 知识图维护 |
| WORKSPACE_CLEANUP_JOB | 每日 04:00 | 归档工作区 |
| STALE_WORKSPACE_DETECT_JOB | 每30分钟 | 检测无活跃会话的工作区 |
| DORMANT_AGENT_JOB [新] | 每30分钟 | 自动休眠超时智能体 |
| CREDENTIAL_CLEANUP_JOB [新] | 每日 02:00 | 清理过期凭据 |

---

## 八、Python API（12个模块，99+函数）

| 模块 | 函数数 | 说明 |
|------|--------|------|
| connection.py | 4 | 连接池、JSON清洗 |
| config.py | — | 统一配置数据类 |
| security.py | 4 | 数据脱敏、可逆加密、密码哈希 |
| memory_api.py | 8 | 记忆CRUD + 衰减 + 强化 |
| knowledge_api.py | 7 | 知识CRUD + 图操作 + 边管理 |
| agent_api.py | 17 | 智能体+凭据+休眠+池化 [新+8] |
| task_plan_api.py | 6 | 任务计划 + 步骤 + 依赖 |
| harness_api.py | 6 | Harness模板CRUD + 实例化 + 派生 |
| graph_api.py | 9 | 属性图API（GRAPH_TABLE） |
| workspace_api.py | 14 | 工作区 + 上下文链 + 交接 + 恢复 |
| spec_api.py [新] | 10 | 规格CRUD + 计划关联 + 验证 + 派生 |
| collab_api.py [新] | 10 | 协作组CRUD + 成员 + 共享记忆 |

---

## 九、Web 可视化（8个页面）

| 页面 | URL | 功能 |
|------|-----|------|
| 知识 | /knowledge | 列表/图双视图，行内详情展开 |
| 记忆 | /memory | 列表/图双视图，类别过滤 |
| 智能体 | /agents | Bootstrap Tabs：注册表/会话/协作 |
| 任务 | /tasks | Accordion折叠，步骤详情，工具I/O |
| 工作区 | /workspaces | 可展开详情行，上下文时间线 |
| 图探索 | /graph | 统计卡片，搜索，vis-network，详情面板 |
| 规格 [新] | /specs | 规格列表，计划关联，详情视图 |
| 协作 [新] | /collab | 组列表，成员管理，共享记忆 |

**UI特性**: 暗色主题 | 中英双语 | 5分钟自动登出 | 侧边栏导航 | ID悬停显示全文

**登录**: admin / admin123

---

## 十、测试结果

```
Oracle Memory System v2.3.0 - 完整测试套件
============================================================
  连接:         6/6 通过
  记忆:         8/8 通过
  知识:         8/8 通过
  智能体:       8/8 通过
  图:           8/8 通过
  Harness:      6/6 通过
  安全:         5/5 通过
  工作区:      12/12 通过
  规格:         9/9 通过 [新]
  协作:        12/12 通过 [新]
  凭据:         9/9 通过 [新]
总计: 99/99 全部通过
```

---

## 十一、版本演进

| 版本 | 日期 | 说明 |
|------|------|------|
| **v2.3.0** | 2026-05-24 | 规格驱动开发、智能体弹性管理、协作组 |
| v2.2.1 | 2026-05-23 | 模板化可视化、侧边栏导航、图探索 |
| v2.2.0 | 2026-05-20 | 工作区与上下文连续性、JRD可更新视图 |
| v2.1.0 | 2026-05-19 | 表分区、复合主键、属性图API |
| v2.0.0 | 2026-05-15 | 统一架构重写、oracledb驱动 |
| v1.x | 2026-04-05 | 初始版本 |

---

## 十二、升级指南

v2.3.0 与 v2.2.x 向后兼容，升级步骤：

1. 执行 1_schema.sql — 新增表、分区、列
2. 执行 2_api.sql — 创建新PL/SQL包
3. 执行 3_jobs.sql — 添加新调度作业
4. 更新Python文件 — 复制 spec_api.py、collab_api.py、更新版 agent_api.py
5. 更新可视化 — 复制 server.py、specs.html、collab.html

无需数据迁移，v2.2.x 现有数据完全兼容。

---

## 十三、关键设计决策

| 决策 | 说明 |
|------|------|
| 规格复用ENTITIES | 统一存储、分区、JRD；SPEC_META引用分区与HARNESS_META一致 |
| 规格↔计划多对多 | SPEC_PLAN_LINKS；UK=(SPEC_ID,PLAN_ID,LINK_TYPE) |
| DORMANT vs POOL | DORMANT保留身份（临时休眠），POOL无状态（凭据跟随用户） |
| POOL匹配算法 | skills_tags交集匹配，选最佳匹配 |
| 协作组Mode C | 组级共享WS + LEAD/CONTRIBUTOR个人WS；OBSERVER无个人WS |
| CONSTRAINTS保留字 | Oracle保留字，必须双引号"CONSTRAINTS" |
| oracledb命名绑定 | JSON列表上命名绑定导致ORA-01745；使用位置绑定或短名 |

---

## 十四、数据库连接

| 参数 | 值 |
|------|-----|
| DSN | //10.10.10.130:1521/openclaw |
| 用户 | openclaw / hermes |
| Python | /home/linuxbrew/.linuxbrew/bin/python3.14 (3.14.5, oracledb 4.0.0) |
| 可视化 | http://10.10.10.136:8000 (admin/admin123) |

---

## 十五、统计对比

| 指标 | v2.2.1 | v2.3.0 | 增量 |
|------|--------|--------|------|
| 表 | 22 | 27 | +5 |
| JRD视图 | 4 | 6 | +2 |
| PL/SQL包 | 5 | 7 | +2 |
| 调度作业 | 9 | 11 | +2 |
| Python模块 | 10 | 12 | +2 |
| API函数 | ~80 | ~99 | +19 |
| 测试文件 | 9 | 12 | +3 |
| 测试数 | 61 | 99 | +38 |
| 可视化页面 | 6 | 8 | +2 |
