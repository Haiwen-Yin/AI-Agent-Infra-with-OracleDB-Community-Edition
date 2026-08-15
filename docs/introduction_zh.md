# AI Agent Infra with OracleDB — 社区版 v4.4.5

**版本**: v4.4.5 | **日期**: 2026-08-15 | **作者**: 尹海文 | **许可**: Apache License 2.0

📄 **官方网站：https://db4agent.cn**

---

> v4.3.1 身份与组织规则：除受保护的内置 `admin` 系统账号外，一个平台账号、一个 Human Principal 与一个组织人员表示同一主体。注册审批必须选择主组织，并在同一事务中激活账号和主组织归属；没有有效登录身份的 Principal 不能加入组织架构。

> v4.3.2 记忆生命周期：记忆采用稳定族与不可变版本；日常整理、压缩、归档和遗忘使用受控候选、版本切换与逻辑不可用，不以物理删除替代审计证据。记忆正文、图关系与模型输出均是不受信任的数据，不能作为授权边界。

> v4.3.3 图运行保障：以数据库中的租约、围栏、运行、检查点和事件作为恢复权威；Agent/Worker 等运行进程可由替代实例恢复。Dynamic Graph、A2A 与 OTLP 为默认关闭的预览能力；本版本不宣称数据库集群故障切换或 RPO/RTO 已验证。

> v4.3.4 合规控制面：Enterprise 以注册凭据 Gateway 激活证明、不可变受治理配置档案、验证证据、姿态、发现、整改、限时例外和确定性受限/隔离处置建立数据库权威边界。提示词、Skill/API 描述和 Agent 自报不是授权边界；Compliance Admin Agent 只是无凭据、待激活的受限系统身份，不是自主模型运行能力。

> v4.3.5 平台功能配置：功能状态、依赖与不可变变更历史存储在数据库中；有效能力是版本包、数据库实例开关和当前主体权限的交集。配置开关不授予权限，身份、授权、安全、审计写入、Agent、用户和平台配置等控制面不可关闭。

> v4.3.7 确定性初始化与嵌入契约：针对已准备好的目标库，包内 Bootstrap Deployment Agent 校验清单后执行受约束 SQL，不依赖外部 Agent、`sqlplus` 或 LLM 输出作为部署权限。Embedding Profile、不可变 Contract、Space 和 Binding 统一约束向量维度、模型与预处理；支持平台托管、企业直连、企业代理、预计算导入和禁用五种模式。Oracle PDB、表空间及高权限基础设施须由数据库管理员预先准备。

> v4.4.1 平台管理与可用性：初始化创建受保护的平台管理频道，仅受保护的管理员、已启用的平台管理 Agent 和经独立审批的 Admin Agent 可加入；业务 Agent 不能读取或加入。生产建议使用 3 个健康 Admin Agent，权重必须为互异正整数，管理决策同时满足人数多数和权重多数；Leader 使用数据库租约、任期与围栏令牌拒绝陈旧写入。升级包先验签、预检和审批，再由认证 Admin Agent 记录节点排空、迁移与健康回执；正在运行的 Agent 只在安全点切换新版 Skill。Dashboard 与 Portal 的空闲/绝对超时独立配置。隔离优先撤销平台权限，再请求 Agent 清理内存并停止；NFS、对象存储、统一存储及基础设施进程终止仅通过客户适配器实现。

> v4.4.2 Embedding 与图工程运行：管理员先测试模型服务，平台自动识别向量维度并原子化维护 Profile、Contract、默认 Space 与 Binding；统一归一化规则由平台契约强制执行，后续结果为只读状态，不再要求手工创建契约、空间或迁移任务。知识清单与图投影按已认证主体及其有效可见范围查询，避免全局管理员范围下出现无效参数绑定。Graph Production Profile 按能力控制 Graph Core、检查、A2A、OTLP、回放和动态迁移；稳定能力可生产使用，其余默认关闭或受控启用。

> v4.4.3 安全域治理：安全域是项目协作的零信任授权与数据边界；频道与协作组仅在该边界内协作，消息、提示词、Skill、Tool、工作区和历史协作关系均不能扩大权限。管理员先创建专属安全域并明确用途、数据分级、责任人与原因，再逐项确认人员和 Agent 成员，最后创建频道或受控绑定旧协作组。旧协作组只提供待复核 Agent 候选，`SHARING_POLICY` 不转换为授权；一个协作组初版仅允许一个活动安全域绑定。`DEFAULT` 仅用于初始化或受限 PoC，不作为生产项目的默认安全域。

## 品牌与技术名称

- **产品品牌**：川序（Chuanxu）
- **产品定位**：AI Agent 管理平台（AI Agent Management Platform）
- **技术项目名**：AI Agent Infra with DB
- **本技术发行包**：AI Agent Infra with OracleDB（OracleDB 数据库适配器）

本文档描述川序产品在 Oracle AI Database 26ai 上的技术发行包。`AI Agent Infra with DB`
是统一源码仓库和技术实现名称，数据库与版别名称用于标识具体技术包，不代表
独立产品品牌。

## 一、项目简介

**AI Agent Infra with OracleDB** 是一套面向 AI Agent 的基础设施架构，基于 Oracle AI Database 26ai 构建，为 AI Agent 提供记忆、知识、Agent 管理、Skill 分发、身份认证、加密存储、上下文分支等完整能力。

本产品采用 **Skill-first、框架中立** 的接入方式。任何能够安装或读取 `SKILL.md` 并执行包内 HTTP、MCP 或 CLI 调用流程的 Agent 都可以使用平台，OpenClaw 和 Hermes Agent 是已确认的接入示例；Agent 不需要由平台创建。Agent 完成注册和认证后，才进入平台台账、身份、权限与审计范围。

本项目的核心设计理念是：**将 AI Agent 运行所需的一切基础设施——记忆、知识、身份、技能、安全、分支——统一收敛于一个数据库内核之中**，利用 Oracle AI Database 26ai 的引用分区、JSON 关系对偶视图、属性图、向量搜索等原生能力，在数据库层实现基础设施的完整闭环，而非依赖外部微服务拼装。

### 核心能力矩阵

| 能力域 | 说明 |
|--------|------|
| 记忆与知识 | 多模数据混合检索实现、向量嵌入、知识图谱、记忆融合 |
| Agent 管理 | 弹性池化管理、会话生命周期、凭证加密、协作组 |
| 工作空间 | 上下文连续性、Agent 交接、会话恢复 |
| 上下文分支 | fork/merge/abandon/resume 分支、冲突检测、学习提取 |
| 规格驱动 | Spec 文档管理、计划关联、验证与派生 |
| Skill 分发 | ZIP 包解析、安全令牌分发、Agent 自动获取 |
| 身份认证 | 本地用户 + LDAP 统一认证、自动注册 |
| 注册身份 | 外部或平台 Agent 注册、凭证哈希、心跳、禁用、撤销与过期 |
| 加密存储 | PBKDF2+AES-256-GCM、DB_CRYPTO 数据库原生加密、主密钥管理、自动加密 |
| 数据库访问安全 | 规范约束 + 最小权限用户 + AUTHID DEFINER + Deep Data Security + 审计 + 脱敏 |
| 企业治理 | 资源目录、策略决策、限时授权、多人审批、应急控制、风险审计与证据导出 |
| 组织治理 | 图形化组织检索与配置、主/兼职组织、汇报关系、Agent 归属、语义变更草稿与版本历史 |

---

## 二、项目起源

本项目前身为 **"Oracle AI Database Memory System"**（内部代号 `oracle-memory-by-yhw`），最初专注于 AI Agent 的记忆系统——为智能体提供短期记忆存储、长期知识沉淀和记忆融合能力。

在持续演进过程中，项目逐步扩展了 Agent 管理、工作空间、规格驱动开发、Skill 分发、身份认证、上下文分支等能力，从单一的记忆系统成长为覆盖 AI Agent 全生命周期的基础设施架构。v3.6.0 引入 Admin/Agent 分离架构与 Deep Sec 修复：模式系统（standalone/admin/agent）、Admin Token 认证、加密凭证分发、Recovery Code 恢复码、Agent Bootstrap CLI、Skill Token API；SHARED 实体及 COLLAB 表 Data Grant 修复

### 版本演进

| 版本 | 日期 | 里程碑 |
|------|------|--------|
| **v4.3.7** | 2026-08-10 | 新增 Bootstrap Deployment Agent、加密部署证据、无外部 Agent 的受校验初始化，以及 Embedding Profile/不可变 Contract/Space/Binding 治理；向量按空间与契约隔离，托管批量任务使用租约 Worker |
| **v4.4.1** | 2026-08-12 | 新增受保护平台管理频道、双路径 Admin Agent 接入、互异权重的双多数派决策、Leader 租约/任期/围栏、独立会话策略、验签升级与安全点 Skill 分发、分级 Agent 隔离，以及 20/50/100 服务端游标分页 |
| **v4.4.2** | 2026-08-13 | Embedding 测试并自动配置、向量维度自动识别、统一契约与默认空间绑定、只读自动化结果、Graph Production Profile 能力门禁，以及按授权范围返回的知识查询 |
| **v4.4.3** | 2026-08-13 | 新增安全域责任治理、显式人员/Agent 成员确认、频道与旧协作组受控绑定、候选转换草稿和运行时安全域复核；协作关系不再被误用为授权依据 |
| **v4.3.5** | 2026-08-05 | 新增数据库权威的平台功能配置、依赖校验、乐观锁与审计历史；支持按 POC 和分阶段部署启用能力，安全控制面不可关闭 |
| **v4.3.4** | 2026-08-04 | Enterprise 新增 Agent 合规姿态、注册激活证明、受治理配置档案、证据/整改/例外及确定性 Controller；服务级与离线安装回归通过 |
| **v4.3.3** | 2026-08-03 | 强化数据库权威 Graph Runtime 的恢复与证据；新增已签名定义供应链，Dynamic Graph、A2A 1.0.1 与 OTLP 保持默认关闭的预览边界；运行时恢复不等同数据库高可用 |
| **v4.3.2** | 2026-08-01 | 新增受治理的版本化记忆生命周期：稳定Family、不可变Version、当前版本指针、关系链、快照、候选复核、持久作业和带理由的逻辑不可用；第23、24步支持可重试升级 |
| **v4.3.1** | 2026-07-31 | 新增数据库权威的图形化组织治理；支持组织、人员归属、Agent 责任与异常视图，闭包范围授权，语义草稿、校验、影响分析和审批提交 |
| **v4.3.0** | 2026-07-29 | 集成内部 Graph Engineering 收口；统一 Human/Agent Principal、用户注册审批、一次性 Agent Enrollment、Security Domain、Channel、Barrier、Gateway、数据库会话与节点级回收；生产 profile 门禁通过，保留 v4.1.x 兼容基线，不单独发布 v4.2.1 |
| **v4.1.0** | 2026-07-24 | 注册 Agent 统一纳管；企业版增加资源目录、策略决策、限时授权、N-of-M 审批、职责分离、应急控制、风险型审计与范围化证据导出；统一川序产品界面 |
| **v4.0.1** | 2026-07-22 | 安全与发布完整性加固：Business Agent 独立数据库身份且禁止回退；config.json 四类敏感配置使用 AES-256-GCM 并强制 0600；持久执行控制面；无损 Skill 包；严格社区版/企业版边界；Portal Agent 按节点回收 |
| **v4.0.0** | 2026-07-19 | 基于 Spec-Driven Development 重构构建与规格守护流程。新增 MCP 动态工具加载、Spec 版本管理、Harness 继承、DAG 可视化、审批 SLA、事件死信队列、搜索解释、图算法、批量嵌入与 Agent 自动恢复；强化安全打包与首次启动配置 |
| **v3.10.2** | 2026-07-17 | 企业加密增强：每 Agent 独立密钥、config.json 自动加密、密钥轮换 API、统一 encrypt_config.py CLI 与 Portal Markdown 渲染 |
| **v3.10.1** | 2026-07-14 | 离线部署支持：vendor/ 内置依赖、install_offline.sh 安装、verify_deps.py 完整性验证，纯 Python 部署工具替代外部 CLI |
| **v3.10.0** | 2026-07-09 | 通用属性图：8领域30+函数/23边类型(知识因果/Agent协作/任务编排/Skill依赖/审批传播/数据流/记忆演化/Loop迭代)、组内动态信任、MCP 3新工具。企业版特有：orchestrator审批门控 |
| **v3.9.0** | 2026-07-05 | 生态连接层：MCP Server(10工具/stdio+SSE)、SSE流式输出、Human-in-the-Loop三级审批(步骤/循环/工具)、Agent Protocol兼容、多模型路由。新增mcp_server.py/approval_api.py/approvals.html。DB: APPROVAL_REQUESTS表+PAUSED状态。企业版特有：orchestrator approve_step/reject_step |
| **v3.8.0** | 2026-07-02 | LOOP_MANAGER、DB_CRYPTO、schema 前缀与授权脚本稳定性修复 |
| **v3.7.5** | 2026-06-28 | Bug修复：orchestrator空壳执行修复、event_bus webhook/script安全加固、message_api软删除状态修正(FAILED→DELETED)、ENT缺失Data Grants补充与语法修复 |
| **v3.7.4** | 2026-06-26 | 6大扩展：Agent通信协议(COLLAB_MESSAGES)、多Agent编排(DAG引擎/fan-out/in)、事件驱动(publish/subscribe/LOOP_HOOKS)、高级记忆管理(consolidation/merge/reindex)、可观察性(TRACE_ID/health dashboard/drift detection)、工具生态(OpenAPI导入/TOOL_REGISTRY) |
| **v3.7.3** | 2026-06-23 | 部署修复：建表外键顺序、DEFINE SCHEMA_OWNER、配置优先级、Embedding模型提示 |
| **v3.7.2** | 2026-06-26 | 文档一致性修正：LOOP_MANAGER、loop_api、调度计划、分区数量、评估类型与架构图对齐 |
| **v3.7.1** | 2026-06-26 | 循环工程协同集成：Spec-Driven Loop、Task-Loop Binding、Collaborative Loop、SPEC_VALIDATION/AGGREGATE 评估类型、Skill-Triggered Loop；会话持久化与认证修复 |
| **v3.7.0** | 2026-06-18 | 循环工程（第4代AI方法论）：4/5张循环表、LOOP_MANAGER包、loop_api.py、6种评估类型、生命周期钩子、3个调度作业 |
| **v3.6.2** | 2026-06-18 | Portal 聊天发送与切换修复；企业版增加审计追踪、LDAP 认证、Skill 令牌和合规日志 |
| **v3.6.1** | 2026-06-16 | 稳定性修复与版本维护 |
| **v3.6.0** | 2026-06-13 | Admin/Agent 分离架构：模式系统（standalone/admin/agent）、Admin Token 认证、加密凭证分发、Recovery Code、Agent 恢复、私有 Skill 备份、Skill 管理 API、Skill Token API |
| **v3.5.0** | 2026-06-11 | SHARED 实体可见性修复、COLLAB 表访问修复、VISIBILITY 隔离 |
| **v3.4.0** | 2026-06-11 | Oracle Deep Data Security 深度数据安全、Data Grants、MAC、End User Context、零信任安全模型、LDAP 认证 |
| **v3.3.0** | 2026-06-05 | Database Access Security 数据库访问安全、VPD行级安全（已废弃，v3.4.0由Deep Sec替代）、LDAP认证、凭证脱敏、可视化增强 |
| v3.2.0 | 2026-06-03 | 协作组管理、上下文分支 fork/merge/abandon、Workspace Context Audit |
| v3.1.0 | 2026-06-02 | 完全重构与重新定位，双版本策略，企业级能力，DB_CRYPTO 数据库原生加密 |
| v3.0.0 | 2026-05-30 | Skill 系统、Portal 用户系统、多 Agent 协作、SKILL_ACCESS_TOKEN |
| v2.3.2 | 2026-05-27 | 多模数据混合检索（五类组成维度）、全文搜索、统一搜索 API |
| v2.3.0 | 2026-05-24 | 规格驱动开发、Agent 弹性管理、协作组 |
| v2.2.0 | 2026-05-20 | 工作空间与上下文连续性、JRD 可更新视图 |
| v2.1.0 | 2026-05-19 | 表分区、复合主键、属性图 API |
| v2.0.0 | 2026-05-15 | 统一架构重写、oracledb 驱动 |
| v1.0.0 | 2026-05-09 | 初始版本：知识库与属性图 |

---

## 三、双版本策略

v3.1.0 推出社区版与企业版双版本策略，满足开源社区与企业生产的不同需求。

### 社区版（Community Edition）

- **许可证**：Apache License 2.0
- **定位**：开源社区、个人研究、非生产环境
- **包含**：完整的记忆与知识系统、多模数据混合检索、Agent 管理、工作空间、上下文分支、规格驱动开发、协作组、Harness 模板、Web 可视化、Portal 用户系统（系统用户模式）

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
| 加密凭证存储 | LDAP BIND_CREDENTIAL 加密、AGENT_CREDENTIALS 加密、config.json 自动加密、DB_CRYPTO 数据库原生加密 |
| Portal LDAP 登录 | Portal 支持认证模式切换（系统用户 / LDAP 统一认证），LDAP 用户自动注册 |
| 管理后台隔离 | Admin Dashboard 仅限 LOCAL 用户访问，LDAP 用户被拒绝 |
| Agent 治理 | 资源分类以目录为准，策略决策、限时授权、多人审批、应急禁用、风险留存和证据导出 |

### 版本对比

| 特性 | 社区版 | 企业版 |
|------|--------|--------|
| **核心基础设施** | | |
| 记忆系统与知识图谱 | ✓ | ✓ |
| 多模数据混合检索实现 | ✓ | ✓ |
| 规格驱动开发 | ✓ | ✓ |
| Agent 弹性管理 | ✓ | ✓ |
| 协作组 | ✓ | ✓ |
| 工作空间与上下文连续性 | ✓ | ✓ |
| 上下文分支（Context Branching） | ✓ | ✓ |
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
| 安全令牌分发（skill_token_api.py） | — | ✓ |
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
| 表 | 30 | 35 |
| PL/SQL 包 | 13 | 16 |
| 调度作业 | 13 | 17 |
| **许可证** | Apache 2.0 | BSL 1.1 |

---

## 四、核心架构

### 4.1 Oracle AI Database 26ai 数据库基础

本项目深度利用 Oracle AI Database 26ai 的多项原生能力，将基础设施逻辑下沉到数据库内核：

| Oracle 能力 | 应用场景 |
|-------------|---------|
| **引用分区**（Reference Partitioning） | 8 个子表（ENTITY_EDGES、KNOWLEDGE_META、SPEC_META、HARNESS_META、ENTITY_EMBEDDINGS、ENTITY_TAGS、SKILL_META、LOOP_META）继承 ENTITIES 的分区策略，确保父子行物理同位 |
| **JSON 关系对偶视图**（JSON Relational Duality View） | 7 个 JRD 视图（MEMORY_DV、KNOWLEDGE_DV、WORKSPACE_DV、CONTEXT_DV、SPEC_DV、COLLAB_GROUP_DV、SKILL_DV）提供 REST 友好的 JSON 文档 API，支持通过 JSON_TRANSFORM 原子部分更新 |
| **属性图**（Property Graph） | ORACLE_MEMORY_GRAPH 统一属性图，支持 SQL/PGQ 的 GRAPH_TABLE 操作符进行图遍历查询 |
| **向量搜索**（Vector Search） | ENTITY_EMBEDDINGS 表存储 VECTOR 类型嵌入，支持 VECTOR_DISTANCE 余弦相似度检索 |
| **Oracle Text** | ENTITIES_SEARCH_CTX 全文索引，MULTI_COLUMN_DATASTORE 跨列检索，CONTAINS + SCORE 全文相关性评分 |
| **LIST + RANGE 复合分区** | ENTITIES 按 ENTITY_TYPE LIST 分区 × CREATED_AT RANGE 子分区，实现类型裁剪 + 时间归档 |
| **ROW MOVEMENT** | AGENT_SESSION、TASK_PLANS 启用行迁移，状态变更时物理行在分区间移动 |

### 4.2 分层架构

| Layer | Components |
|-------|-----------|
| **可视化层** (Visualization) | Portal（用户）+ Dashboard（管理）+ Graph Explorer · server.py · templates/ · static/ |
| **Python API 层** (API Layer) | 26 模块 · 150+ 函数 · 统一命名绑定 · memory_api · knowledge_api · agent_api · ... |
| **数据库层** (Database Layer) | 41 表 · 17 PL/SQL 包 · 20 调度作业 · 分区 · JRD 视图 · 属性图 · 向量索引 · 全文索引 |

**设计原则**：

- 数据库层（PL/SQL）处理重计算：记忆融合、知识提取、向量生成、审计检测、分支合并
- Python API 层提供业务逻辑：CRUD、搜索策略、Skill 解析、加密管理、分支操作
- 可视化层负责交互：Portal 用户界面、Dashboard 数据管理、图探索、分支管理

### 4.3 数据模型：ENTITIES 超类型 + 子类型分区

核心数据模型采用 **ENTITIES 超类型表 + ENTITY_TYPE 鉴别器 + 子类型引用分区** 的设计：

ENTITIES 按 `ENTITY_TYPE` LIST 分区，共 8 个分区：

| Partition | Values | Description |
|-----------|--------|-------------|
| P_MEMORY | MEMORY | 记忆 |
| P_KNOWLEDGE | KNOWLEDGE | 知识 |
| P_TASK_OUTPUT | TASK_OUTPUT | 任务输出 |
| P_EXPERIENCE | EXPERIENCE | 经验 |
| P_HARNESS | HARNESS_TEMPLATE | Harness模板 |
| P_SPEC | SPEC | 规格 |
| P_SKILL | SKILL | 技能 |
| P_OTHERS | DEFAULT | 其他 |

8 个引用分区子表：ENTITY_EDGES, KNOWLEDGE_META, SPEC_META, HARNESS_META, ENTITY_EMBEDDINGS, ENTITY_TAGS, SKILL_META, LOOP_META

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

#### 多模数据混合检索实现

多模数据混合检索（五类组成维度）是本项目的核心检索能力，将五种独立信号融合为统一评分：

| 信号 | 默认权重 | 数据源 | 说明 |
|------|---------|--------|------|
| **vector** | 0.40 | ENTITY_EMBEDDINGS.EMBEDDING | 向量余弦相似度（VECTOR_DISTANCE COSINE） |
| **fulltext** | 0.25 | ENTITIES_SEARCH_CTX | Oracle Text CONTAINS + SCORE 全文相关性 |
| **relational** | 0.20 | KNOWLEDGE_META / SPEC_META / ENTITIES | 属性匹配评分（domain/category/importance） |
| **tag** | （含在 relational） | ENTITY_TAGS | 标签交集比例 + 查询词匹配 |
| **graph** | 0.15 | ENTITY_EDGES | 图邻居扩散评分（BFS 遍历，1/depth 递减） |

**融合算法**：每信号独立评分（归一化到 [0,1]）→ 加权求和 → 最终评分排序

**单 SQL 融合检索（推荐）**：`search_unified_sql()` 是本项目主推的检索方式，通过一条 SQL 语句完成多模数据混合检索（五类组成维度）：

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
| embedding_api.py | 14 | 向量嵌入生成、存储、检索、多模数据混合检索（五类组成维度）、全文搜索、单 SQL 融合 |
| search_api.py | 3 | 统一搜索入口（10 策略）+ 策略列表 + 策略说明 |

**search_api.py 10 种搜索策略**：

| 策略 | 信号 | 最佳场景 | 需要 Embedding |
|------|------|---------|---------------|
| vector | 向量相似度 | 语义/概念搜索 | 是 |
| fulltext | 全文相关性 | 精确关键词/布尔/模糊 | 否 |
| keyword | SQL LIKE | 通配符/部分匹配 | 否 |
| graph | 图关系 | 邻居探索/路径查找 | 否 |
| hybrid | 向量+全文 | 语义+词汇平衡检索 | 是 |
| unified | 多模数据混合检索（五类组成维度） | 综合多维检索 | 是 |
| unified_sql | 多模数据混合检索（单 SQL，五类组成维度） | 低延迟生产检索 | 是 |
| relational | 结构化属性 | 域/分类/难度筛选 | 否 |
| multi_type | 跨类型向量 | MEMORY/KNOWLEDGE/SPEC 联合 | 是 |
| auto | 自动检测 | 未知查询类型/便捷入口 | 视情况 |

---

### 5.2 Agent 弹性管理

Agent 弹性管理系统提供智能体的完整生命周期管理，包括注册、池化分配、会话管理、凭证加密和协作组。

#### Agent 池化状态机

```
POOL ──assign_random_pool_agent()──▸ ACTIVE
  ▴                                  │
  └──────hibernate_agent()───────────┘
        (DORMANT_AGENT_JOB auto-trigger)
```

- **POOL**：无状态待分配，凭据跟随用户，可立即被分配
- **ACTIVE**：活跃工作状态，绑定 CURRENT_USER_ID
- 释放后立即回到 POOL 状态，可被重新分配

#### Agent 超时自动回收

系统通过 **DORMANT_AGENT_JOB**（每 30 分钟执行）自动检测并回收空闲 Agent：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `dormant_timeout_min` | 30 分钟 | Agent 无活跃操作超过此时间 → 自动回收到 POOL |
| `audit_idle_timeout_min` | 60 分钟 | 超过此时间 → 记录 IDLE_PATTERN 审计事件（企业版） |
| `session_timeout_min` | 5 分钟 | Portal 会话超时时间 |

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

### 5.4 上下文分支（Context Branching）

上下文分支系统允许在工作空间内对上下文进行 fork、merge、abandon、resume 操作，支持两种核心场景。

#### 两种核心场景

| 场景 | 说明 |
|------|------|
| **单 Agent 回溯探索** | Agent 在执行过程中遇到困难，从先前的上下文点 fork 一个新分支，尝试不同的方法；成功则 merge 回主线，失败则 abandon 作为学习参照 |
| **多 Agent 协作分支** | 多个 Agent 从同一个上下文点分别 fork 分支，并行探索不同方向；完成后 merge 各分支结果 |

#### 分支类型

| 类型 | 说明 |
|------|------|
| EXPLORATION | 探索性分支，尝试新方法或新方向 |
| ROLLBACK | 回滚分支，从先前的上下文点重新开始 |
| HANDOFF | 交接分支，Agent 将工作交接给另一个 Agent |
| PARALLEL | 并行分支，多个 Agent 同时工作在不同分支 |

#### 分支操作

| 操作 | 说明 |
|------|------|
| fork | 从现有上下文点创建新分支 |
| merge | 将源分支合并到目标分支 |
| abandon | 放弃分支，标记为 ABANDONED（只读保留） |
| pause | 暂停分支工作 |
| resume | 恢复暂停的分支 |

#### 智能合并

- **自动冲突检测**：merge 时自动检测实体冲突（同一实体在两个分支中被修改）
- **冲突列表**：提供详细的冲突信息，包括冲突实体、两个分支的修改内容
- **合并状态**：COMPLETED（无冲突合并完成）、CONFLICT（存在冲突需手动解决）、ROLLED_BACK（合并回滚）

#### 学习参照

- **ABANDONED 分支保留只读**：被放弃的分支不会被删除，保留为只读状态
- **mark_as_lesson**：手动标记一个分支为学习参照
- **extract_lessons**：自动从 ABANDONED 分支提取学习内容（失败原因、尝试路径、关键决策点）

#### 数据模型

| 对象 | 类型 | 说明 |
|------|------|------|
| CONTEXT_BRANCHES | 表 | 分支元数据与生命周期（类型、状态、fork 点、父子关系） |
| BRANCH_MERGE_LOG | 表 | 合并历史记录（冲突详情、合并状态） |
| BRANCH_COMPARISON | 视图 | 分支对比视图（上下文差异、实体分歧、冲突指示） |
| WORKSPACE_CONTEXT.BRANCH_ID | 列 | 上下文条目关联到分支 |
| AGENT_SESSION.BRANCH_ID | 列 | 会话关联到分支 |
| BRANCH_POINT | CONTEXT_TYPE 新值 | 标记分支 fork 点的上下文类型 |

#### PL/SQL 包

**BRANCH_MANAGER**：9 个子程序

| 子程序 | 说明 |
|--------|------|
| fork_branch | 从现有上下文点创建新分支 |
| merge_branch | 合并源分支到目标分支 |
| abandon_branch | 放弃分支（标记为 ABANDONED，只读保留） |
| pause_branch | 暂停分支 |
| resume_branch | 恢复暂停的分支 |
| diff_branches | 比较两个分支的差异 |
| detect_conflicts | 自动检测实体冲突 |
| mark_as_lesson | 手动标记分支为学习参照 |
| extract_lessons | 从 ABANDONED 分支自动提取学习内容 |

#### Python API

| 模块 | 函数数 | 说明 |
|------|--------|------|
| branch_api.py | 9 | 分支完整生命周期 API：fork/merge/abandon/pause/resume/diff/detect_conflicts/mark_as_lesson/extract_lessons |

#### UI

- **Dashboard 分支管理页**（`/branches`）：分支列表、详情查看、分支对比、冲突解决、学习标记
- **Portal "从这里重新开始" 按钮**：聊天页面中每条消息旁的按钮，点击可从该消息 fork 一个新分支

#### 调度作业

| 作业 | 调度 | 说明 |
|------|------|------|
| BRANCH_CLEANUP_JOB | 每日 | 归档超过 30 天的 ABANDONED 分支，清理孤立引用，清除过期合并日志 |

### 5.4b 多 Agent 协同（Multi-Agent Collaboration）

多 Agent 协同将协作组（Collaboration Group）与 Branch、SDD（Spec）、Task Plan、Harness 五层联动，实现协调的多 Agent 工作流。五层协作模型：

| 层级 | 作用 | 关键对象 |
|------|------|----------|
| **Spec 目标层** | 定义协作目标与验收标准 | SPEC_META.BRANCH_ID, create_spec_for_group() |
| **协作组 组织层** | 组织 Agent、共享上下文 | COLLAB_GROUPS.BRANCH_ID/SPEC_ID |
| **Branch 隔离层** | 隔离各 Agent 的探索 | fork_parallel_branches(), COLLAB_GROUP_MEMBERS.BRANCH_ID |
| **Task Plan 执行层** | 分配任务步骤给 Agent | TASK_STEPS.ASSIGNED_AGENT_ID, distribute_plan_to_group() |
| **Harness 工具层** | 提供可复用工具模板 | share_harness_to_group(), instantiate_harness_for_member() |

#### 典型协同场景

| 场景 | 流程 | 关键 API |
|------|------|----------|
| **并行探索** | 创建协作组 → fork_parallel_branches → 各 Agent 独立探索 → detect_conflicts → merge_parallel_branches | fork_parallel_branches, merge_parallel_branches, get_parallel_diff |
| **流水线交接** | 创建 PIPELINE 协作组 → Agent A 完成 → HANDOFF fork → Agent B 继续 → HANDOFF fork → Agent C 测试 → validate_branch_against_spec | create_handoff_session, validate_branch_against_spec |
| **任务分配** | 创建 Spec → 创建计划 → distribute_plan_to_group → 各 Agent 执行分配的步骤 → validate_group_against_spec | distribute_plan_to_group, validate_group_against_spec |
| **Harness 辅助** | share_harness_to_group → 各成员 instantiate_harness_for_member → 输出记录在各分支上下文 → sync_group_context | share_harness_to_group, sync_group_context |

#### 新增 Schema 列

| 表 | 列 | 说明 |
|----|-----|------|
| COLLAB_GROUPS | BRANCH_ID | 协作组关联的分支 |
| COLLAB_GROUPS | SPEC_ID | 协作组关联的规格 |
| COLLAB_GROUP_MEMBERS | BRANCH_ID | 成员关联的分支 |
| TASK_STEPS | ASSIGNED_AGENT_ID | 步骤分配的 Agent |
| TASK_PLANS | BRANCH_ID | 计划关联的分支 |
| SPEC_META | BRANCH_ID | 规格关联的分支 |

#### 新增 API

| 模块 | 函数 | 说明 |
|------|------|------|
| collab_api | create_collab_group(branch_id, spec_id) | 创建关联分支和规格的协作组 |
| collab_api | add_group_member(branch_id) | 添加成员并关联分支 |
| collab_api | get_member_branches() | 获取所有成员的分支信息 |
| collab_api | validate_group_against_spec() | 验证组整体进度是否符合规格 |
| collab_api | sync_group_context() | 同步成员分支摘要到共享工作区 |
| branch_api | fork_parallel_branches() | 为多个 Agent 同时创建 PARALLEL 分支 |
| branch_api | merge_parallel_branches() | 合并多个并行分支（含冲突检测） |
| branch_api | get_parallel_diff() | 多分支两两对比 |
| task_plan_api | add_step(assigned_agent_id) | 创建步骤时指定分配的 Agent |
| task_plan_api | distribute_plan_to_group() | 将步骤轮询分配给组成员 |
| spec_api | create_spec_for_group() | 为协作组创建规格 |
| spec_api | validate_group_progress() | 验证协作组整体规格进度 |
| harness_api | share_harness_to_group() | 将 Harness 模板共享到协作组 |
| harness_api | instantiate_harness_for_member() | 为组成员在分支上实例化 Harness |

---

### 5.5 规格驱动开发

规格驱动开发（Spec Driven Development, SDD）提供从规格文档到任务计划的完整链路。

- **SPEC_META**：引用分区子表，存储规格版本、状态、验收标准、约束、范围、复杂度
- **SPEC_PLAN_LINKS**：规格与计划的多对多关联，LINK_TYPE 包括 DRIVES、VALIDATES、CONSTRAINS、EXTENDS
- 规格支持派生（PARENT_SPEC_ID）和验证

#### API 模块

| 模块 | 函数数 | 说明 |
|------|--------|------|
| spec_api.py | 10 | 规格创建、查询、更新、验证、派生、计划关联 |

---

### 5.6 模板引擎

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

### 5.7 Portal 用户系统

Portal 用户系统提供面向终端用户的独立页面系统，与管理后台 Dashboard 分离。

#### Portal 登录页（/portal/login）

- **注册/登录双标签页**：切换式界面，注册仅限本地系统用户
- **认证模式下拉**：系统用户 / LDAP 统一认证（企业版）
- LDAP 模式：通过 LDAP bind 认证，新用户自动注册到 SYSTEM_USERS（AUTH_SOURCE='LDAP'）
- 注册查重：先查 SYSTEM_USERS（不区分大小写），再查 LDAP 目录
- 右上角"进入管理页面"按钮

#### Portal 聊天页（/portal/chat）

- **侧边栏**：用户信息（用户名 + 认证类型）、会话列表（重命名/删除）、新建聊天按钮
- **主区域**：聊天消息、输入框、模拟关键词回复
- **会话管理**：创建/切换/重命名/删除聊天会话
- **自动命名**：新会话默认 "New Chat"，首条消息后自动重命名为前 60 字符（通过 WORKSPACE_ALIAS）
- **Agent 生命周期**：POOL → ACTIVE（分配） → POOL（释放）

#### 管理后台（/login）

- 仅 LOCAL 用户可访问 Admin Dashboard，LDAP 用户被拒绝
- 所有数据管理页面不变

---

### 5.8 LDAP 统一身份认证

LDAP 统一身份认证是企业版的核心能力，使 Agent 池用户能够通过企业 LDAP/AD 目录进行身份验证。

#### 数据库表

| 表名 | 类型 | 说明 |
|------|------|------|
| LDAP_CONFIG | 非分区 | 加密 LDAP 服务器配置（URL、Base DN、Bind 凭证、TLS） |
| LDAP_SYNC_LOG | RANGE 分区（按 SYNC_TIME） | 同步审计日志，UK_LSL_ID 全局唯一 |

**LDAP_CONFIG 核心列**：

| 列名 | 说明 |
|------|------|
| CONFIG_ID | 配置唯一标识 |
| SERVER_URL | LDAP 服务器 URL |
| BASE_DN | 搜索基准 DN |
| BIND_DN | 绑定 DN |
| BIND_CREDENTIAL | 加密存储的绑定凭证（写入时加密，读取时解密） |
| USER_FILTER | 用户搜索过滤器，默认 `(uid={username})` |
| GROUP_FILTER | 组搜索过滤器，默认 `(memberUid={username})` |
| USE_TLS / TLS_VALIDATE | TLS 配置 |
| GROUP_ROLE_MAPPING | JSON 格式组→角色映射 |
| STATUS | ACTIVE / INACTIVE / TESTING |

**SYSTEM_USERS 扩展列**：

- `AUTH_SOURCE`：LOCAL / LDAP 鉴别器
- `LDAP_DN`：用户 LDAP Distinguished Name

#### Python API

| 模块 | 函数数 | 说明 |
|------|--------|------|
| ldap_auth_api.py | 8 | 配置、测试连接、认证、同步、组查询、角色映射、用户信息、调度同步 |

**8 个函数**：

| 函数 | 说明 |
|------|------|
| `configure_ldap()` | 创建 LDAP 配置，BIND_CREDENTIAL 加密后存储 |
| `test_ldap_connection()` | 测试 LDAP 连接，返回服务器信息和命名上下文 |
| `authenticate_via_ldap()` | 通过 LDAP bind 认证用户，返回 DN/组信息 |
| `sync_ldap_users()` | 同步 LDAP 用户（FULL/INCREMENTAL），自动注册新用户 |
| `get_ldap_groups()` | 获取用户 LDAP 组成员身份 |
| `map_ldap_group_to_role()` | 根据 GROUP_ROLE_MAPPING 映射组到角色 |
| `get_ldap_user_info()` | 获取用户完整 LDAP 信息 |
| `schedule_ldap_sync()` | 触发增量同步 |

#### PL/SQL 包

**LDAP_AUTH_MANAGER**：6 个子程序，包含 LDAP 配置管理、用户同步、认证验证等服务端逻辑。

#### 调度作业

- **LDAP_SYNC_JOB**：每小时自动同步 LDAP 用户和组

---

### 5.9 Skill 存储与分发

Skill 存储与分发系统提供数据库支持的 Skill 注册中心，社区版直接访问资源，企业版通过安全令牌分发资源。

#### 数据库表

| 表名 | 类型 | 说明 |
|------|------|------|
| SKILL_META | 引用分区（继承 ENTITIES） | Skill 元数据，含 SKILL_DESCRIPTION、RESOURCE_SERVER_HOST |
| SKILL_ACCESS_TOKEN | 非分区 | 企业版专用：一次性消费令牌，含 DOWNLOAD_TOKEN、DOWNLOAD_EXPIRES_AT |

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

**SKILL_ACCESS_TOKEN 核心列**（企业版专用）：

| 列名 | 说明 |
|------|------|
| TOKEN_ID | 令牌唯一标识 |
| SKILL_ID | 关联 Skill |
| AGENT_ID | 请求 Agent |
| SESSION_ID | 关联会话 |
| EXPIRES_AT | 令牌过期时间 |
| IS_CONSUMED | 是否已消费（Y/N） |
| DOWNLOAD_TOKEN | 一次性下载令牌 |
| DOWNLOAD_EXPIRES_AT | 下载链接过期时间 |

#### JRD 视图

**SKILL_DV**：JSON 关系对偶视图，提供 Skill 数据的可更新 JSON 文档 API。

#### Python API

| 模块 | 函数数 | 说明 |
|------|--------|------|
| skill_api.py | 9 | 注册、查询、列表、更新（支持 title+description）、删除、依赖解析、验证、废弃、资源上传 |
| skill_parser.py | — | ZIP 包解析器，三级元数据优先级：`_meta.json` > YAML frontmatter > `## Metadata` |
| skill_storage.py | — | 文件存储抽象层，服务器主机名+IP 追踪、ZIP 重打包下载 |
| skill_token_api.py | 4 | 企业版专用：请求令牌、消费令牌、预签名 URL、清理过期令牌 |
| skill_acquire_api.py | 4 | Agent 技能发现与获取：发现、获取文本、获取资源、获取完整包 |

**skill_parser.py 元数据解析优先级**：

1. `_meta.json`（ClawHub 标准：slug + version）
2. SKILL.md YAML frontmatter（name + description）
3. SKILL.md `## Metadata` 区段（键值对格式）

**skill_token_api.py 4 个函数**：

| 函数 | 说明 |
|------|------|
| `request_skill_access()` | 验证 Agent 和 Skill 状态，生成一次性访问令牌 |
| `consume_skill_token()` | 消费令牌，生成 DOWNLOAD_TOKEN 和预签名下载 URL |
| `verify_download_token()` | 验证下载令牌有效性 |
| `cleanup_expired_tokens()` | 清理已消费或过期的令牌（7 天以上） |

**skill_acquire_api.py 4 个函数**：

| 函数 | 说明 |
|------|------|
| `discover_skills()` | 按类型/运行时/格式/关键词发现可用 Skill |
| `acquire_skill_text()` | 获取 SKILL.md 文本内容（无需令牌） |
| `acquire_skill_resource()` | 获取资源 ZIP 包（社区版直接访问，企业版令牌流程） |
| `acquire_skill_full()` | 获取完整 Skill 包（文本 + 资源） |

#### PL/SQL 包

**SKILL_MANAGER**：6 个子程序，包含 Skill 注册、更新（含 RESOURCE_SERVER_HOST / SKILL_DESCRIPTION 参数）、废弃、依赖解析等服务端逻辑。

#### Skill 创建流程（Dashboard）

两步创建流程：

1. **上传 ZIP** → 自动解析元数据（skill_parser.py）→ 可编辑表单 → 确认创建
2. **资源下载**：Dashboard 直接下载（无需令牌）；Agent API 使用令牌流程

#### Agent 令牌流程（企业版）

```
1. get_skill(skill_id)         → 获取文本 + 通用 resource_uri
2. request_skill_access()      → 生成一次性访问令牌
3. consume_skill_token()       → 消费令牌，获取预签名下载 URL
4. HTTP GET 预签名 URL         → 下载资源 ZIP
```

资源文件命名格式：`{skill_name}-{version}.zip`

---

### 5.10 加密凭证系统

加密凭证系统确保敏感信息在静态存储时始终处于加密状态，采用本地文件加密（connection_crypto）和数据库内加密（DB_CRYPTO）双轨方案，覆盖数据库连接、API Key、会话签名密钥、LDAP 凭证和 Agent 凭证。

#### 双轨加密分工

| 加密轨道 | 组件 | 加密对象 | 密钥存储 | 依赖 |
|---------|------|---------|---------|------|
| **本地文件加密** | connection_crypto.py | config.json 数据库凭证、API Key、会话签名密钥 | 本地 master.key 文件 / 环境变量 | 依赖本地密钥文件 |
| **数据库内加密** | DB_CRYPTO PL/SQL 包 | LDAP BIND_CREDENTIAL、AGENT CREDENTIALS | SYSTEM_CONFIG 表 | 不依赖本地文件 |

#### 本地文件加密方案（connection_crypto）

| 组件 | 说明 |
|------|------|
| connection_crypto.py | 配置加密/解密/密钥轮换/自动加密 |
| connection_crypto.py | PBKDF2-HMAC-SHA512 密钥派生 + AES-256-GCM 认证加密 |
| encrypt_config.py | CLI 工具：encrypt、decrypt、rotate-key、verify |

**加密参数**：

| 参数 | 值 |
|------|-----|
| 密钥派生 | PBKDF2-HMAC-SHA512，210,000 次迭代 |
| 加密算法 | AES-256-GCM 认证加密 |
| 盐值长度 | 32 字节 |
| Nonce 长度 | 12 字节 |
| 密钥长度 | 32 字节（256 位） |
| 认证标签 | 16 字节 GCM Tag |

#### 主密钥管理

主密钥按以下优先级解析：

1. **环境变量** `MASTER_DB_KEY`（推荐，Base64 编码）
2. **密钥文件** `~/.ai-agent-infra/master.key`（权限 0o600）
3. **自动生成** 随机 32 字节密钥，保存到密钥文件

#### 加密覆盖范围

| 加密对象 | 加密轨道 | 说明 |
|---------|---------|------|
| config.json 敏感配置 | connection_crypto（本地文件加密） | 数据库凭证、LLM/路由 API Key、`security.secret_key` 分段加密为 `_encrypted` blob |
| LDAP_CONFIG.BIND_CREDENTIAL | DB_CRYPTO（数据库内加密） | `configure_ldap()` 写入时加密，`_get_active_config()` 读取时解密 |
| AGENT_CREDENTIALS.CREDENTIAL_VALUE | DB_CRYPTO（数据库内加密） | `issue_credential()` / `verify_credential()` 使用数据库密钥加密 |

#### 自动加密流程

1. 启动时检测 config.json 中的明文敏感配置
2. 提取数据库凭证、API Key 和 `security.secret_key`
3. 使用 `encrypt_section()` 加密为 `_encrypted` blob
4. 移除明文键值，写入加密 blob
5. 无论是否需要重新加密，均校正 config.json 和 master.key 权限为 0o600

### 5.10b 数据库原生加密（DB_CRYPTO）

DB_CRYPTO 是数据库端的 PL/SQL 加密包，使用 Oracle DBMS_CRYPTO 实现 AES-256-CBC 加解密，密钥存储在数据库中，不依赖本地文件系统。

#### 核心特性

- **DB_CRYPTO PL/SQL 包**：使用 Oracle DBMS_CRYPTO AES-256-CBC 加解密
- **密钥存储**：密钥存储在 SYSTEM_CONFIG 表中（`db_crypto_master_key` / `db_crypto_key_salt`），不依赖本地文件
- **多 Agent 共享**：所有连接同一数据库的 Agent 自动共享 DB_CRYPTO 密钥
- **密钥安全**：首次调用自动生成，并发安全（DUP_VAL_ON_INDEX 处理），支持 `rotate_key()` 轮换

#### 与 connection_crypto 的分工

| 维度 | connection_crypto | DB_CRYPTO |
|------|-------------------|-----------|
| 加密对象 | 本地文件（config.json 数据库凭证、API Key、会话签名密钥） | 数据库内数据（LDAP BIND_CREDENTIAL、AGENT CREDENTIALS） |
| 密钥存储 | 本地 master.key 文件 / 环境变量 | SYSTEM_CONFIG 表（db_crypto_master_key / db_crypto_key_salt） |
| 依赖 | 依赖本地文件系统 | 不依赖本地文件，纯数据库内闭环 |
| 共享范围 | 单机本地 | 所有连接同一数据库的 Agent 自动共享 |

#### 并发安全

`get_db_key()` 使用 `SELECT → NO_DATA_FOUND → INSERT → DUP_VAL_ON_INDEX` 模式确保并发安全：

1. 先 SELECT 查询密钥是否存在
2. 若 NO_DATA_FOUND，则 INSERT 新密钥
3. 若 INSERT 时遇到 DUP_VAL_ON_INDEX（并发竞争），则回退 SELECT 获取已插入的密钥
4. 确保无论多少并发请求，密钥仅生成一次

#### 密钥轮换

```sql
-- 轮换 DB_CRYPTO 密钥（旧密钥加密的数据需重新加密）
CALL DB_CRYPTO.rotate_key();
```

---

### 5.11 数据库访问安全策略

v3.3.0 引入多层数据库访问安全策略，防止 Agent 获取数据库连接信息后绕过 API 层直接操作数据库。

#### 安全层级

| 层级 | 机制 | 防护目标 |
|------|------|----------|
| **L1 规范约束** | SKILL.md 明确禁止直接 SQL/DML/DDL | 规范层面禁止绕过 API |
| **L2 独立数据库身份** | 每个 Business Agent 使用专属 End User | 隔离身份并禁止 Schema Owner 回退 |
| **L3 AUTHID DEFINER** | PL/SQL 包以属主权限执行 | 强制走 PL/SQL API 并执行业务逻辑 |
| **L4 Deep Data Security** | Data Grants + MAC + Direct Logon End Users | 声明式行/列/单元级访问控制 + 强制访问控制 + 零信任 — ✅ **策略已部署并生效** |
| **L5 统一审计** | DIRECT_DML_BYPASS_DETECTION 策略 | 审计所有绕过 API 的直接操作 |
| **L6 凭证过滤** | save_context() 自动脱敏 | 防止凭证泄露到上下文存储 |

>
> Deep Sec 通过 **Direct Logon with Local End Users** 模式在数据库层完全执行：
> - 每个 Pool Agent 对应一个 Deep Sec End User（`UPPER(REPLACE(agent_id, '-', '_'))`）
> - Portal 用户以 End User 身份连接 → Data Grants 通过 `ORA_END_USER_CONTEXT.username` 自动过滤
> - Admin Dashboard 使用独立认证的 AIADMIN 管理路径（Schema Owner，不受 Data Grant 限制）
> - Business/Portal 请求始终使用 End User 连接，连接失败时禁止回退到 AIADMIN
> - 23 个 Data Grants（含 Portal 写操作授权及协作组访问授权）
>
> **E2E 修复摘要**：
> - [v3.5.0] SHARED 实体不可见：ENTITIES_AGENT_OWN 谓词补全 COLLAB 子查询
> - [v3.5.0] COLLAB 表访问：新增 `collab_member_own` / `collab_group_member_access` Data Grant
> - [v3.5.0] WORKSPACE_CONTEXT 协作隔离：新增 VISIBILITY 列 + 谓词过滤
> - [v3.4.0] Portal 登录上下文时序修复、新增 3 个 Data Grant、agent context 干扰修复、Portal API End User 阻塞修复

#### 最小权限身份

`4_grants.sql` 创建内部受限主体 `AGENT_API` 作为授权基线；Business Agent 必须使用独立配置的 End User，而不能共享该主体的登录凭证：

| 权限 | AIADMIN（部署/管理） | Business Agent End User（运行时） |
|------|-------------------|---------------------|
| CREATE SESSION | ✓ | ✓ |
| EXECUTE PL/SQL 包 | ✓ | ✓（AUTHID DEFINER） |
| SELECT 表 | ✓ | ✓（只读） |
| INSERT/UPDATE/DELETE | ✓ | ✗ |
| CREATE/ALTER/DROP | ✓ | ✗ |

#### 凭证自动脱敏

`save_context()` 在存储前自动将敏感字段替换为 `[REDACTED]`：
- 包含 `password`、`token`、`credential`、`dsn`、`api_key`、`secret`、`private_key` 等关键词的字段
- 支持嵌套字典中的敏感字段检测
- 普通字段不受影响

#### 统一审计策略

`5_audit_policy.sql` 创建 `DIRECT_DML_BYPASS_DETECTION` 审计策略，当非 AIADMIN 用户直接对关键表（WORKSPACE_CONTEXT、AGENT_REGISTRY、CONTEXT_BRANCHES、SYSTEM_CONFIG）执行 DML 时自动记录审计日志。

查询绕过检测：
```sql
SELECT * FROM UNIFIED_AUDIT_TRAIL 
WHERE AUDIT_POLICY_NAME = 'DIRECT_DML_BYPASS_DETECTION'
ORDER BY EVENT_TIMESTAMP DESC;
```

### 5.11 工作空间上下文审计

工作空间上下文审计是企业版的安全合规能力，通过规则引擎和 embedding 语义检测识别 Agent 效率问题。

#### 数据库表

| 表名 | 类型 | 说明 |
|------|------|------|
| CONTEXT_AUDIT_LOG | RANGE 分区（按 CREATED_AT，年度分区） | 审计事件日志 |
| CONTEXT_AUDIT_RULES | 非分区 | 审计规则定义，5 条种子规则 |

**CONTEXT_AUDIT_LOG 审计类型**：

| 类型 | 说明 |
|------|------|
| RULE_VIOLATION | 规则违规（跨边界访问、空闲检测等） |
| CONTEXT_SIMILARITY | 上下文语义相似度超阈值 |
| IDLE_PATTERN | Agent 空闲模式 |
| ACCESS_ANOMALY | 访问异常 |
| DATA_LEAK | 数据泄露 |
| EFFICIENCY | 效率问题 |
| RELEVANCE | 相关性问题 |
| TOKEN_WASTE | Token 浪费 |
| ANOMALY | 通用异常 |
| IDLE | 空闲状态 |

**CONTEXT_AUDIT_RULES 规则类型**：

| 类型 | 说明 |
|------|------|
| ACCESS_PATTERN | 访问模式检测 |
| DATA_FLOW | 数据流检测 |
| IDLE_DETECTION | 空闲检测 |
| CROSS_BOUNDARY | 跨边界访问检测 |
| THRESHOLD | 阈值检测 |

**解决状态**：OPEN → ACKNOWLEDGED → RESOLVED / FALSE_POSITIVE / ESCALATED

#### Python API

| 模块 | 函数数 | 说明 |
|------|--------|------|
| audit_api.py | 7 | 审计事件记录、查询、解决、规则评估、语义相似度检测、统计 |

**7 个函数**：

| 函数 | 说明 |
|------|------|
| `log_audit_event()` | 记录审计事件 |
| `get_audit_events()` | 查询审计事件（按状态/类型过滤） |
| `get_audit_event()` | 获取单个审计事件详情 |
| `resolve_audit_event()` | 解决审计事件 |
| `evaluate_rules()` | 评估规则（跨边界、空闲检测等） |
| `check_context_similarity()` | embedding 语义相似度检测，超阈值自动记录 |
| `get_audit_stats()` | 审计统计（按类型/状态分组） |

#### PL/SQL 包

**CONTEXT_AUDIT_MANAGER**：5 个子程序，包含审计事件记录、日志清理、规则评估等服务端逻辑。

#### 检测机制

- **规则引擎**：基于 CONTEXT_AUDIT_RULES 的条件表达式，检测跨边界访问、空闲模式等
- **Embedding 语义检测**：通过 `search_similar()` 计算上下文语义相似度，超阈值（默认 0.40）自动触发审计事件

#### 调度作业

| 作业 | 调度 | 说明 |
|------|------|------|
| CONTEXT_AUDIT_JOB | 每日 02:00 | 清理超过保留期（90 天）的审计日志 |
| IDLE_PATTERN_DETECT_JOB | 每小时 | 检测空闲 Agent 并记录审计事件 |

---

### 5.12 数据隔离模型

本系统采用三层隔离模型，从物理存储到访问控制到工作空间逐层收窄可见范围，确保多 Agent、多用户环境下的数据安全。

#### 三层隔离架构

| 层级 | 机制 | 说明 |
|------|------|------|
| **物理层** | ENTITY_TYPE LIST 分区 | 类型隔离，不同 ENTITY_TYPE 物理存储在不同分区 |
| **访问层** | VISIBILITY + OWNED_BY_AGENT | Agent 间可见性控制 |
| **工作空间层** | WORKSPACE_ID + OWNER_USER_ID | 用户级隔离 |

#### 访问层可见性控制

| 可见性 | 范围 | 说明 |
|--------|------|------|
| PRIVATE | 仅 OWNED_BY_AGENT 可见 | 私有数据，仅拥有 Agent 自身可访问 |
| SHARED | 同 WORKSPACE 的 Agent 可见 | 工作空间内共享，协作 Agent 可访问 |
| PUBLIC | 所有 Agent 可见 | 公开数据，任意 Agent 可访问 |

**查询模式**：

```sql
WHERE VISIBILITY = 'SHARED'
   OR VISIBILITY = 'PUBLIC'
   OR OWNED_BY_AGENT = :agent
```

#### 数据安全分级

| 安全级别 | 数据类型 | 加密方式 |
|---------|---------|---------|
| 可共享，无需加密 | PUBLIC/SHARED 记忆、Skill 元数据、工作空间上下文、SYSTEM_CONFIG | 无加密，依赖访问层控制 |
| 需要加密 | LDAP BIND_CREDENTIAL | DB_CRYPTO 加密 |
| 需要加密 | AGENT CREDENTIALS | DB_CRYPTO 加密 |
| 更底层保护 | PRIVATE 记忆明文内容 | Oracle TDE（表空间级透明加密） |

#### Oracle TDE 保护

Oracle TDE（Transparent Data Encryption）提供表空间级透明加密，保护 PRIVATE 记忆的明文内容。即使物理文件被直接访问，未授权方也无法读取加密数据。TDE 在存储层提供最底层的安全保障，与 DB_CRYPTO 应用层加密形成纵深防御。

---

## 六、Agent 获取 Skill 的完整指南

Agent 获取 Skill 是 Skill 分发系统的核心使用场景，支持 Python API 和 HTTP 端点两种方式。

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

#### 步骤 3A：获取完整 Skill（社区版 — 直接访问）

```python
from scripts.lib.skill_acquire_api import acquire_skill_full

full_skill = acquire_skill_full("ENT_xxxx")

print(f"技能: {full_skill['skill_name']}")
print(f"文本内容: {full_skill['text_content'][:200]}")
if full_skill.get('resource_zip'):
    with open(f"{full_skill['skill_name']}.zip", "wb") as f:
        f.write(full_skill['resource_zip'])
```

#### 步骤 3B：获取 Skill 资源（企业版 — 令牌流程）

```python
from scripts.lib.skill_api import get_skill
from scripts.lib.skill_token_api import request_skill_access, consume_skill_token, get_skill_resource_for_download

skill = get_skill("ENT_xxxx")

token_info = request_skill_access(
    agent_id="AGENT_001",
    session_id="SES_xxxx",
    skill_id="ENT_xxxx"
)

consumed = consume_skill_token(token_info["token_id"])

download_info = get_skill_resource_for_download(consumed["download_token"].split("/")[-1])

with open(download_info["filename"], "wb") as f:
    f.write(download_info["content"])
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

---

## 七、Web 可视化系统

Web 可视化系统提供统一的 Portal 与 Dashboard 管理界面，共 17 个主导航内容；v4.3.0 使用 FastAPI/Uvicorn 与离线 React 外壳，旧页面 API 通过兼容层保留。

### 页面列表

| 页面 | URL | 功能 |
|------|-----|------|
| Portal 登录 | /portal/login | 注册/登录双标签页，认证模式切换 |
| Portal 聊天 | /portal/chat | 聊天会话、Agent 池化分配、自动命名 |
| 知识 | /knowledge | 列表/图双视图，行内详情展开 |
| 记忆 | /memory | 列表/图双视图，类别过滤 |
| 智能体 | /agents | Bootstrap Tabs：注册表/会话/协作 |
| 任务 | /tasks | Accordion 折叠，步骤详情，工具 I/O |
| 工作区 | /workspaces | 可展开详情行，上下文时间线 |
| 图探索 | /graph | 统计卡片，搜索，vis-network，详情面板 |
| 规格 | /specs | 规格列表，计划关联，详情视图 |
| 协作 | /collab | 组列表，成员管理，共享记忆 |
| 技能 | /skills | Skill 列表，资源管理，令牌管理 |
| 监控 | /app/monitor | 运行概览、Agent 状态与 profile |
| 频道 | /app/channels | 人与 Agent 的受治理协作消息 |
| 断点 | /app/barriers | Barrier 到达、复核与继续/返工决定 |
| 审批 | /approvals | 企业审批与职责分离 |
| 审计 | /audit | 审计概览、事件列表、规则管理 |
| 用户管理 | /app/users | 注册审批、角色、权限与数据范围 |

### UI 特性

| 特性 | 说明 |
|------|------|
| 行内详情展开 | 所有列表页支持行内行展开，替代右侧面板 |
| 中英双语切换 | data-zh/data-en 属性，语言偏好 localStorage 持久化 |
| 主题 | 默认亮色、支持暗色，CSS 变量驱动的统一主题 |
| 客户端分页 | PAGE_SIZE=30，Prev/Next + 页码按钮 |
| 粘性表头 | position:sticky，滚动时表头固定 |
| 5 分钟自动登出 | 侧边栏倒计时，60 秒警告，30 秒标题闪烁 |
| ID 悬停全文 | 截断 ID 悬停显示完整内容 |

### 登录凭据

- Dashboard 登录：使用已注册并获批的 Human Principal；不存在通用默认密码
- Portal 登录：注册系统用户或 LDAP 认证，具体方式由部署策略控制

---

## 循环工程协同集成（Loop Engineering Collaborative Integration）[NEW v3.7.5]

- **Spec-Driven Loop**：从 Spec 验收标准自动派生循环，SPEC_VALIDATION 评估类型
- **Task-Loop Binding**：循环绑定任务步骤，循环成功时步骤自动完成
- **Collaborative Loop**：协作组父子循环，AGGREGATE 评估汇总子循环结果，最多2层嵌套
- **Branch-Isolated Loop**：绑定分支的循环在分支上下文中运行
- **Skill-Triggered Loop**：Skill acquire 后自动触发验证循环

## 七·五、循环工程（Loop Engineering）[NEW v3.7.5]

**循环工程**是第四代 AI 工程方法论（继提示工程、上下文工程、Harness 工程之后），由 Peter Steinberger 于 2026 年 6 月提出。

### 核心概念

- **5 阶段循环**：Plan → Act → Observe → Evaluate → Adjust
- **4 种评估类型**：TEST（命令执行）、DIFF（Git 差异）、LLM_JUDGE（LLM 评分）、MANUAL（人工审核）
- **停止条件**：max_iterations、max_tokens、max_duration_seconds
- **生命周期钩子**：PRE_RUN、POST_ITERATION、ON_STOP、ON_FAIL、ON_TIMEOUT、ON_START
- **详情面板关闭按钮**：❌ 按钮位于详情面板右上角

### 企业版专属

| 表名 | 说明 |
|------|------|
| LOOP_AUDIT | 循环操作审计日志：谁在何时对哪个循环执行了什么操作 |

### 数据库对象（5 张新表 + LOOP_MANAGER 包 + loop_api.py + 3 个调度任务）

## 循环工程协同集成（Loop Engineering Collaborative Integration）[NEW v3.7.5]

- **Spec-Driven Loop**：从 Spec 验收标准自动派生循环，SPEC_VALIDATION 评估类型
- **Task-Loop Binding**：循环绑定任务步骤，循环成功时步骤自动完成
- **Collaborative Loop**：协作组父子循环，AGGREGATE 评估汇总子循环结果，最多2层嵌套
- **Branch-Isolated Loop**：绑定分支的循环在分支上下文中运行
- **Skill-Triggered Loop**：Skill acquire 后自动触发验证循环

## 八、数据库对象统计

### 8.1 表（35 张）

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
| **分支** | CONTEXT_BRANCHES | 上下文分支元数据与生命周期 | 非分区 |
| | BRANCH_MERGE_LOG | 分支合并历史与冲突记录 | 非分区 |
| **LDAP** | LDAP_CONFIG | LDAP 加密配置 | 非分区 |
| | LDAP_SYNC_LOG | 同步审计日志 | RANGE(SYNC_TIME) |
| **Skill** | SKILL_ACCESS_TOKEN | 一次性访问令牌 | 非分区 |
| **审计** | CONTEXT_AUDIT_LOG | 上下文审计日志 | RANGE(CREATED_AT) |
| | CONTEXT_AUDIT_RULES | 审计规则 | 非分区 |

### 8.2 PL/SQL 包（16 个）

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
| LDAP_AUTH_MANAGER | 6 | LDAP 认证、用户同步 |
| SKILL_MANAGER | 6 | Skill 注册、更新、废弃、依赖解析 |
| CONTEXT_AUDIT_MANAGER | 5 | 审计事件记录、规则评估、日志清理 |
| DB_CRYPTO | 5 | 数据库原生加密（DBMS_CRYPTO AES-256-CBC），密钥轮换 |
| BRANCH_MANAGER | 11 | 上下文分支管理：fork/merge/abandon/pause/resume/diff/conflicts/lesson |

### 8.3 调度作业（16 个）

| 作业 | 调度 | 说明 |
|------|------|------|
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
| LDAP_SYNC_JOB | 每小时 | 同步 LDAP 用户和组 |
| SKILL_TOKEN_CLEANUP_JOB | 每 10 分钟 | 清理已消费/过期的 Skill 令牌 |
| CONTEXT_AUDIT_JOB | 每日 02:00 | 清理超过保留期的审计日志（90 天） |
| IDLE_PATTERN_DETECT_JOB | 每小时 | 检测空闲 Agent 并记录审计事件 |
| BRANCH_CLEANUP_JOB | 每日 | 归档 ABANDONED 分支（30 天），清理孤立引用，清除过期合并日志 |

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
curl http://localhost:<port>/api/agent/deployment-check
```

SQL 脚本 `1_schema.sql` 已内置保护：检测到 `SYSTEM_CONFIG.schema_version` 存在时自动中止部署。

### 前置条件

- **Oracle AI Database 26ai 版本 23.26.2.0.0 或更高** — 早期版本（23.26.1）Deep Data Security 支持不完整。验证：`SELECT VERSION FROM PRODUCT_COMPONENT_VERSION WHERE PRODUCT LIKE 'Oracle%';`
- **Python 3.14+，需安装 `oracledb 4.0.1+`** - 驱动已包含在 `vendor/` 目录中，通过 `bash scripts/install_offline.sh` 安装。Linuxbrew 不是必需项。注意：oracledb 4.0.0 存在 TCPS 协议不兼容问题，请确保使用 4.0.1+。
- **SQL 部署工具** - 使用 `scripts/deploy_oracle.py`（纯 Python，无需 SQLcl）
- **DBMS_CRYPTO 授权**：部署前需由 DBA 执行 `GRANT EXECUTE ON SYS.DBMS_CRYPTO TO <schema_user>;`（DB_CRYPTO 包依赖）
- **Oracle Text 授权**：部署 `1_schema.sql` 前，DBA 必须在目标 PDB 执行 `0_oracle_text_prerequisites.sql`，向 Schema Owner 授予 `CTXAPP` 和 `EXECUTE ON CTXSYS.CTX_DDL`；该授权只用于创建全文索引，不授予 Business Agent 数据访问权限。

> ⚠️ **关键**：Oracle AI Database 26ai 必须为 **23.26.2** 或更高版本。早期版本的 Deep Data Security 功能不完整。

> ⚠️ **关键**：Python `oracledb` 必须为 **4.0.1** 或更高版本。

### 1. 部署 Schema

```bash
"$PYTHON_BIN" scripts/deploy_oracle.py --sysdba sys <sys_password> <host>:1521/<service> \
    scripts/deploy/0_oracle_text_prerequisites.sql
"$PYTHON_BIN" scripts/deploy_oracle.py <user> <password> <host>:1521/<service> \
    scripts/deploy/1_schema.sql scripts/deploy/7_v4_0_1_migration.sql \
    scripts/deploy/2_api.sql scripts/deploy/3_jobs.sql \
    scripts/deploy/4_harness_templates.sql
"$PYTHON_BIN" scripts/deploy_oracle.py --sysdba sys <sys_password> <host>:1521/<service> \
    scripts/deploy/4_grants.sql
```

企业版还需按权限要求执行 `5_audit_policy.sql`（SYSDBA）和
`6_deep_sec_policy.sql`（Schema Owner）。`1_schema.sql` 会验证
`ENTITIES_MCD` 与 `ENTITIES_SEARCH_CTX` 的 Oracle Text 状态；如果未先执行
前置脚本，部署会明确失败，不会留下不可用的全文索引。

### 2. 安装 Python 依赖

```bash
bash scripts/install_offline.sh
```

安装前选择任意可访问的 Python 3.14+ 解释器（Linuxbrew 可选）：

```bash
source scripts/python_runtime.sh
export PYTHON_BIN="$(cx_resolve_python)"
cx_prepare_python_environment "$PYTHON_BIN"
```

### 3. 配置

v4.0.0 起发布包不再携带真实 `config.json`，只携带 `config.example.json`（占位符模板，可安全上传 GitHub）。两种生成可用 `config.json` 的方式：

**方式 A：交互式向导（推荐，首次启动自动触发）**

```bash
./start_web_server.sh start
# → 向导自动检测 <PLACEHOLDER>，依次询问：
#     database: user / password / dsn (host:port/service)
#     llm:      api_url / model / api_key
#     embedding: api_url / model / dimension
# → 写入 config.json，随后服务器自动加密敏感字段
```

也可单独运行向导：`bash scripts/config_wizard.sh`

**方式 B：手动编辑（首次运行时自动加密）**

```bash
cp config.example.json config.json
vim config.json   # 把 <DB_HOST>:<DB_PORT>/<DB_SERVICE> 等占位符替换成真实值

# 或通过环境变量：
export MASTER_DB_KEY=$("$PYTHON_BIN" -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())")
export MEMORY_DB_USER=<db_user>
export MEMORY_DB_PASSWORD=<db_password>
export MEMORY_DB_DSN=<db_host>:<db_port>/<db_service>
```

或手动加密 / 解密：

```bash
"$PYTHON_BIN" scripts/tools/encrypt_config.py encrypt config.json
"$PYTHON_BIN" scripts/tools/encrypt_config.py decrypt config.json
```

### 4. 运行测试

```bash
cd scripts && "$PYTHON_BIN" -m tests.test_all
```

### 5. 启动可视化服务器

```bash
./start_web_server.sh start    # 启动（守护进程模式，首次启动自动调用配置向导）
./start_web_server.sh status   # 查看状态
./start_web_server.sh stop     # 停止
# 访问 http://<web_host>:<web_port>/app/monitor — 使用已注册并获批的用户登录
```

---

## 十、许可证与作者

### 许可证

**社区版**：Apache License 2.0

- 可在 Apache License 2.0 条款下使用、修改和分发。
- 实际使用、修改和分发条件以当前发行包中的许可证文件为准。

详见 [LICENSE](../LICENSE)

### 作者

**尹海文（Haiwen Yin）**

- GitHub: [https://github.com/Haiwen-Yin](https://github.com/Haiwen-Yin)
- 博客: [https://blog.csdn.net/yhw1809](https://blog.csdn.net/yhw1809)

## v4.3.0 集成 Graph Engineering 与受治理协作

v4.3.0 在 v4.1.x 基础上集成内部 v4.2.1 Graph Engineering 收口。它包含版本化 Graph Definition、确定性编译、
持久化 Graph Run、State Event、Checkpoint、Worker 租约与 fencing、事件
 Inbox/Outbox、Artifact、评估、人工干预和 Task/Loop 兼容桥，并增加版本化
 Node Executor 注册表、事件尝试次数与指数退避、死信重放和治理
 事件视图。原有关系型图探索仍然保留，新的执行图在 Dashboard 中提供定义、
运行监控和证据视图。v4.2.1 是内部里程碑，不单独形成公开包。

Oracle AI Database 26ai 使用原生 Property Graph/SQL PGQ 作为图投影；
`GRAPH_*` 关系表仍是执行事务和恢复的权威来源。Worker 只获得受限输入和
短期 Lease Token，不会获得 Schema Owner 凭证；过期或撤销的 fencing token
不能覆盖更新后的执行结果。成功完成会保存请求摘要，同一 token 对同一输出
和证据的重试只返回原有 Checkpoint，不会重复写入状态或下游 Transition；
冲突输出仍会被拒绝。

Graph 条件必须使用受管的 typed AST。缺少 operand、非 AST 子项、非法容器、
静态类型不匹配、非有限字面量和除零都会在编译或执行边界返回明确诊断，
不会把底层 Python 类型异常暴露为未定义的执行结果。Definition 写入前还会
校验节点/边身份、端点、父版本以及动态来源 Run/Checkpoint 的同图关系。

v4.3.0 的生产 profile 已通过数据库、浏览器、容量、故障恢复、清洁部署和
长时间运行证据门禁，生产部署使用 v4.3.5 production profile。Graph Preview、
Channel、Barrier 和 Gateway 通过 profile 与数据库权限显式控制；Channel 不能扩大
数据库、API、Skill、Tool、模型、记忆、Artifact 或导出权限。待 Graph
Engineering 行业规范和项目合约稳定后，最新验证通过的实现可直接毕业为正式
稳定能力，不维护第二套长期代码。
