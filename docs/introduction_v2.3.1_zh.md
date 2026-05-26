# Oracle AI 数据库记忆系统 v2.3.1

**版本**: v2.3.1 | **日期**: 2026-05-26 | **作者**: 尹海文 | **许可**: Apache License 2.0

> v2.3.1 修复并增强向量检索能力，新增五信号融合检索、全文搜索和统一搜索 API，与 v2.3.0 数据库向后兼容。

---

## 一、v2.3.1 更新内容

### 1. 向量检索修复与增强

修复 v2.0.0 架构重写过程中遗漏的 embedding 生成与向量检索能力：

| 组件 | 修复内容 |
|------|----------|
| EMBEDDING_MANAGER 包 | JSON_QUERY WITH WRAPPER 返回双层方括号 `[[...]]`，导致 TO_VECTOR 失败；改用 SUBSTR 去外层 + TO_VECTOR 变量赋值 |
| embedding_api.py [新] | 全部命名绑定修复：`:1,:2,:3` → `:eid,:etype,:vec`，解决 oracledb thin mode 下 ORA-01722 类型转换错误 |
| EMBEDDING_GENERATION_JOB [新] | 每2小时自动为缺失 embedding 的实体生成向量嵌入 |

**根因分析**: v2.0.0 架构重写时将 ENTITY_EMBEDDINGS 改为引用分区，但 PL/SQL 中 JSON_QUERY WITH WRAPPER 返回的嵌套数组格式与 TO_VECTOR 不兼容。oracledb thin mode 下位置绑定（:1,:2,:3）对 VECTOR 类型列产生隐式类型转换，导致 ORA-01722。

**修复方案**:
- PL/SQL: `SUBSTR(JSON_QUERY(...WITH WRAPPER), 2, LENGTH(...)-2)` 剥离外层方括号
- PL/SQL: 使用 `v_vec VECTOR; v_vec := TO_VECTOR(clean_str);` 变量赋值而非内联转换
- Python: 所有 embedding 相关 SQL 统一使用命名绑定 `:eid, :etype, :vec`

### 2. 五信号融合检索（search_unified）

vector + fulltext + relational + tag + graph 五信号加权融合：

| 信号 | 默认权重 | 说明 |
|------|---------|------|
| vector | 0.40 | 向量余弦相似度（VECTOR_DISTANCE COSINE） |
| fulltext | 0.25 | Oracle Text CONTAINS + SCORE 全文相关性 |
| relational | 0.20 | 属性匹配评分（domain/category/importance） |
| tag | (含在 relational) | 标签交集比例 + 查询词匹配 |
| graph | 0.15 | 图邻居扩散评分（ENTITY_EDGES BFS 遍历） |

**融合算法**: 每信号独立评分（归一化到 [0,1]）→ 加权求和 → 最终评分排序

**过滤支持**: domain、category、tags、graph_seed 等多维过滤

### 3. 全文搜索（search_fulltext）

基于 Oracle Text CONTEXT 索引的全文检索：

| 组件 | 说明 |
|------|------|
| ENTITIES_SEARCH_CTX 索引 [新] | CONTEXT 索引，MULTI_COLUMN_DATASTORE(TITLE, CONTENT)，SYNC ON COMMIT |
| search_fulltext 函数 | CONTAINS + SCORE 全文检索，返回归一化 ft_score |

**查询语法支持**:
- 布尔运算: `AND` / `OR` / `NOT`
- 模糊匹配: `$word`（模糊词）
- 词干搜索: `$word`（英语词干扩展）
- 短语搜索: `"exact phrase"`

### 4. 统一搜索 API（search_api.py）

10种搜索策略的统一入口，AI 智能体可按需选择或自动匹配：

| 策略 | 信号 | 最佳场景 | 需要Embedding |
|------|------|---------|--------------|
| vector | 向量相似度 | 语义/概念搜索 | 是 |
| fulltext | 全文相关性 | 精确关键词/布尔/模糊 | 否 |
| keyword | SQL LIKE | 通配符/部分匹配 | 否 |
| graph | 图关系 | 邻居探索/路径查找 | 否 |
| hybrid | 向量+全文 | 语义+词汇平衡检索 | 是 |
| unified | 五信号融合 | 综合多维检索 | 是 |
| unified_sql | 五信号融合(单SQL) | 低延迟生产检索 | 是 |
| relational | 结构化属性 | 域/分类/难度筛选 | 否 |
| multi_type | 跨类型向量 | MEMORY/KNOWLEDGE/SPEC联合 | 是 |
| auto | 自动检测 | 未知查询类型/便捷入口 | 视情况 |

**LLM上下文经济学**：统一搜索API的深层设计动机是降低检索对LLM上下文的占用与污染。传统做法下，AI智能体需要多次工具调用（先查记忆、再查知识、再查向量相似），每次调用都消耗token并可能用中间噪音污染上下文。统一搜索API将多次调用压缩为一次，减少60-80%的工具调用token开销，保持上下文纯净，让智能体将宝贵的token预算留给推理与决策。

**3个核心函数**:
- `search(query, strategy, ...)` — 统一搜索入口，返回 `{strategy, query, results, count}`
- `list_search_strategies()` — 列出所有可用策略及元数据
- `describe_search_strategy(name)` — 策略详细说明含参数列表

**自动策略检测规则（auto）**:

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

### 5. 新增模块汇总

| 模块 | 函数数 | 说明 |
|------|--------|------|
| embedding_api.py [新] | 14 | Embedding 生成、存储、向量检索、五信号融合、全文搜索 |
| search_api.py [新] | 3 | 统一搜索入口（9策略）+ 策略列表 + 策略说明 |

### 6. 新增测试汇总

| 测试文件 | 测试数 | 说明 |
|----------|--------|------|
| test_embedding.py [新] | 19 | Embedding 生成、检索、批量、删除、维度检测 |
| test_unified_search.py [新] | 31 | 五信号融合检索各信号独立+组合测试，单SQL融合检索测试 |
| test_search_api.py [新] | 42 | 10种策略元数据 + 自动检测 + 调用正确性 + unified_sql + 边界条件 |

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

27张表 | 6个JRD视图 | 8个PL/SQL包 | 12个调度作业
15个Python模块 | 131+ API函数 | 183/183 测试通过
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

## 六、PL/SQL 包（8个）

| 包名 | 子程序数 | 说明 |
|------|---------|------|
| MEMORY_FUSION_ENGINE | 7 | 记忆融合 |
| KNOWLEDGE_BASE_API | 5 | 知识管理 |
| AGENT_PERMISSION_MANAGER | 5 | 权限管理 |
| SESSION_CLEANUP | 4 | 会话清理 |
| WORKSPACE_MANAGER | 10 | 工作区管理 |
| SPEC_MANAGER [新] | 8 | 规格管理 |
| COLLAB_GROUP_MANAGER [新] | 6 | 协作组管理 |
| EMBEDDING_MANAGER [新] | 5 | Embedding生成、查询、余弦相似度、批量、统计 |

---

## 七、调度作业（12个）

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
| EMBEDDING_GENERATION_JOB [新] | 每2小时 | 自动生成缺失的embedding |

---

## 八、Python API（15个模块，131+函数）

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
| embedding_api.py [新] | 15 | Embedding生成、存储、向量检索、五信号融合、单SQL融合、全文搜索 |
| search_api.py [新] | 3 | 统一搜索入口（10策略）+ 策略列表 + 策略说明 |

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
Oracle Memory System v2.3.1 - 完整测试套件
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
  Embedding:   19/19 通过 [新]
  统一搜索:    31/31 通过 [新]
  搜索API:     42/42 通过 [新]
总计: 183/183 全部通过
```

---

## 十一、版本演进

| 版本 | 日期 | 说明 |
|------|------|------|
| **v2.3.1** | 2026-05-26 | 向量检索修复、五信号融合检索、全文搜索、统一搜索API |
| v2.3.0 | 2026-05-24 | 规格驱动开发、智能体弹性管理、协作组 |
| v2.2.1 | 2026-05-23 | 模板化可视化、侧边栏导航、图探索 |
| v2.2.0 | 2026-05-20 | 工作区与上下文连续性、JRD可更新视图 |
| v2.1.0 | 2026-05-19 | 表分区、复合主键、属性图API |
| v2.0.0 | 2026-05-15 | 统一架构重写、oracledb驱动 |
| v1.x | 2026-04-05 | 初始版本 |

---

## 十二、升级指南

v2.3.1 与 v2.3.0 向后兼容，升级步骤：

1. 执行 1_schema.sql — 创建 ENTITIES_SEARCH_CTX 全文索引
2. 执行 2_api.sql — 创建 EMBEDDING_MANAGER 包 + 修复向量检索逻辑
3. 执行 3_jobs.sql — 添加 EMBEDDING_GENERATION_JOB 调度作业
4. 更新Python文件 — 复制 embedding_api.py、search_api.py、更新版其他API
5. 更新测试 — 复制 test_embedding.py、test_unified_search.py、test_search_api.py

无需数据迁移，v2.3.0 现有数据完全兼容。已有 ENTITY_EMBEDDINGS 数据将在 EMBEDDING_GENERATION_JOB 首次运行时自动补全缺失向量。

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
| JSON_QUERY双层方括号 | WITH WRAPPER返回`[[...]]`；用SUBSTR去外层再TO_VECTOR |
| oracledb thin mode VECTOR绑定 | 位置绑定(:1,:2,:3)对VECTOR列产生ORA-01722；必须使用命名绑定(:eid,:etype,:vec) |
| 五信号权重分配 | vector(0.4)主导语义，fulltext(0.25)精确匹配，relational+tag(0.2)结构化，graph(0.15)关系扩散 |
| 全文索引MULTI_COLUMN | ENTITIES_SEARCH_CTX用MULTI_COLUMN_DATASTORE(TITLE,CONTENT)实现跨列全文检索 |
| 自动策略检测 | 基于查询特征（布尔/通配符/词数/过滤条件）自动选择最优搜索策略 |
| tag信号纳入relational | 标签与属性同属结构化信号，合计权重0.2，避免信号碎片化 |
| 图邻近性BFS | 使用ENTITY_EDGES BFS遍历（非GRAPH_TABLE，因复合PK匹配问题），1/depth递减 |
| LLM上下文经济学 | 检索环节多次工具调用造成token浪费和上下文污染；单SQL融合检索将5次调用压缩为1次，减少60-80%工具调用token开销 |
| 单SQL融合检索 | search_unified_sql通过4个CTE（candidates+tag_scores+edge_counts+graph_prox）实现单条SQL完成五信号融合，消除多轮Python-SQL往返 |

---

## 十四、数据库连接

| 参数 | 值 |
|------|-----|
| DSN | //<db_host>:<db_port>/<db_service> |
| 用户 | <db_user> / <db_password> |
| Python | 3.14+ / oracledb 4.0.0 thin mode |
| 可视化 | http://<web_host>:<web_port> |

---

## 十五、统计对比

| 指标 | v2.3.0 | v2.3.1 | 增量 |
|------|--------|--------|------|
| 表 | 27 | 27 | 0 |
| JRD视图 | 6 | 6 | 0 |
| PL/SQL包 | 7 | 8 | +1 |
| 调度作业 | 11 | 12 | +1 |
| Python模块 | 12 | 15 | +3 |
| API函数 | ~99 | ~131 | +32 |
| 测试文件 | 12 | 14 | +2 |
| 测试数 | 99 | 183 | +84 |
| 可视化页面 | 8 | 8 | 0 |
| 全文索引 | 0 | 1 | +1 |
| 搜索策略 | 0 | 10 | +10 |
