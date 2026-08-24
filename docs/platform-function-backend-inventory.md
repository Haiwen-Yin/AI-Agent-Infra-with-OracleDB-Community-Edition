# 川序平台功能与后台实现总账 v4.4.10

> 适用版本：v4.4.10  
> 部署目标：Oracle AI Database、PostgreSQL、YashanDB Enterprise；现场验收应覆盖网络、负载均衡、备份和实例策略。  
> 部署基线：v4.4.10 全新部署；历史迁移仅用于顺序、校验和与审计复现；v4.4.8 已撤回  
> 代码事实源：`shared/web/src/App.tsx`、`shared/web_app.py`、`shared/visualization/server.py`、`shared/lib/`、`adapters/*/deploy/`

## 1. 使用方法与状态定义

本文是平台功能、后台实现和验收证据的单一检查入口。菜单或数据库表存在不等于能力已可生产验收。

| 状态 | 含义 |
|---|---|
| `PRODUCTION` | 当前版本具备明确授权、持久化、错误边界和回归覆盖，可进入三库验收 |
| `PARTIAL` | 主流程可用，但规格中的扩展能力、性能证据或异常闭环尚不完整 |
| `CONTROLLED` | 受功能开关、Production Profile、人工审批或适配器条件约束 |
| `COMPATIBILITY` | 为历史调用保留，不应作为新集成首选 |
| `NOT_IMPLEMENTED` | 规格目标或表结构已出现，但当前没有可验收的完整后台流程 |

所有浏览器入口先经过数据库 Session、CSRF、MFA、入口权限和 `effective_access()`；数据范围继续受组织、Security Domain、直属关系、责任组、Owner/Assigned 等 scope 约束。Agent Gateway 使用独立短期凭据和数据库身份，不继承浏览器 Session。

## 2. 总体实现链

```text
React Dashboard / Portal / Agent Runtime
              |
         FastAPI web_app.py
              |
   显式 v4.3-v4.4 API + legacy compatibility bridge
              |
 shared/lib 领域服务（授权、状态机、租约、审计、投影）
              |
 connection facade -> Oracle / PostgreSQL / YashanDB adapter
              |
 数据库表、包、RLS/VPD/对象授权、迁移日志
```

- `shared/web_app.py` 是新管理面、身份面、平台面和 Agent Gateway 的 HTTP 边界。
- `shared/visualization/server.py` 承载仍在兼容桥后的任务、Workspace、Knowledge、Memory、Skill、Spec、Branch、Loop、Graph、Portal 等历史接口。
- `shared/lib/connection.py` 只用于统一源码导入；六个发布包会替换为所选数据库适配器。
- Enterprise 是构建期功能白名单，不是前端隐藏按钮；Community 不应打包 Enterprise 后台模块。
- `GET /health` 是进程存活探针；`GET /ready` 是数据库与当前控制面迁移就绪探针。

## 3. 管理后台 22 个页面

| 页面与功能 | 主要读取/变更 API | 后台实现 | 权限 / 核心数据对象 | 成熟度与验收 |
|---|---|---|---|---|
| 监控 | `/api/monitor/agents-page`、legacy `/api/stats`、`/api/telemetry/status` | `monitor_api.py`、`trace_api.py` | `agents.read`；`AGENT_REGISTRY`、`AGENT_SESSION`、`TASK_PLANS`、`LOOP_RUNS` | `PRODUCTION`；验证分页、总数/在线口径、stalled 与越权 Agent 不可见 |
| 管理大屏 | `GET /api/wallboard`、定义创建/发布/回滚、`GET /api/model-usage/summary` | `model_usage_api.py`、`model_governance_api.py`、`monitor_api.py` | `wallboard.read/manage`、`model_usage.read`；usage/request、definition version/publication、运行表 | `PRODUCTION`；Viewer 只读；组织范围经 Agent 主责任人和组织闭包解析；运行源失败必须返回 partial/degraded 和不可用值，不能伪装为当前 0；三库门禁校验非零样例及 busy <= online <= total |
| 智能体 | `/api/agents`、状态/归属/派生对象/注册/隔离/下线接口 | `identity_api.py`、`agent_api.py`、`agent_registration.py`、`native_agent_api.py` | `agents.*`；`CX_PRINCIPALS`、`CX_AGENT_RELATIONSHIPS`、`AGENT_REGISTRY`、`CX_AGENT_INSTANCES` | `PRODUCTION`；验证 Human-Owner-Agent 关系、跨域拒绝、逻辑下线保留历史 |
| 任务 | `/api/tasks`、legacy Task Plan/step 控制接口 | `task_plan_api.py`、`orchestrator.py`、`execution_control.py` | `tasks.read/write`；`TASK_PLANS`、`TASK_STEPS`、`TASK_TOOL_CALLS` | `PRODUCTION`；验证状态机、重试、租约和 Agent scope |
| 工作区 | legacy `/api/workspaces` 及 Workspace 变更接口 | `workspace_api.py` | `workspaces.read/write`；`WORKSPACES`、`WORKSPACE_CONTEXT`、`WORKSPACE_TASKS` | `PRODUCTION`；验证隔离模式和私有 Workspace 越权拒绝 |
| 知识 | `/api/knowledge/inventory`、`/api/knowledge`、legacy 检索接口 | `knowledge_api.py`、`search_api.py`、`embedding_api.py` | `knowledge.read/write`；`ENTITIES`、`KNOWLEDGE_META`、Embedding 对象 | `PRODUCTION`，向量能力为 `CONTROLLED`；验证来源、可见性、无跨 Agent 检索 |
| 记忆 | `/api/memory/inventory`、legacy `/api/memory/*`、候选/投影/作业 | `memory_api.py`、`memory_lifecycle.py` | `memory.read/review`；`CX_MEMORY_*`、`ENTITIES` | `PRODUCTION`；验证候选评审、版本谱系、Worker 租约和 dry-run |
| 技能 | `/api/skills`、legacy `/api/admin/skill/*`、Token/获取接口 | `skill_api.py`、`skill_parser.py`、`skill_storage.py`、`skill_acquire_api.py` | `skills.read/write`；`SKILL_META`、包版本、文件哈希、访问 Token | `PRODUCTION`；验证 ZIP 路径安全、哈希、不可变版本和只读物化 |
| 规格 | `/api/specs`、legacy SDD/OpenSpec 接口 | `spec_api.py`、`sdd_api.py`、`sdd_contracts.py` | `specs.read/write`；`SPEC_META`、`CX_SDD_*` | `PRODUCTION`；OpenSpec 是可选输入边界，数据库 Approved Baseline 才是执行事实 |
| 分支 | legacy `/api/branches`、fork/merge/parallel/validation | `branch_api.py`、`scm_adapter_api.py` | `tasks.read`、`branches.write`；`CONTEXT_BRANCHES`、合并/验证记录 | `PRODUCTION`；验证并行隔离、冲突和 SCM 凭据只存引用 |
| 执行组（内部兼容关系） | legacy `/api/collab`、分发/同步/组分支、Loop | `security_domain_api.py` + `collab_api.py` | `CX_DOMAIN_BINDINGS`、`CX_DOMAIN_MEMBERS`、`COLLAB_GROUPS`、成员/分支/工作区 | `COMPATIBILITY`；不是产品授权或知识分组；新流程为 Security Domain -> Channel，运行时可引用执行组；未绑定、跨域或 Agent 非成员均失败关闭 |
| 循环 | legacy `/api/loops`、create/start/pause/resume/stop/iterate | `loop_api.py` | `tasks.read`、`loops.write`；`LOOP_DEFINITIONS`、`LOOP_RUNS`、Hook | `PRODUCTION`；验证终态幂等、Token 累计和 Barrier 等待 |
| 图探索 | legacy `/api/graph/*`、`/api/graphs`、Graph Run/Worker/Event/Assurance | `graph_api.py` 及 `graph_*.py` | `graphs.read` 及 Graph 能力开关；`ENTITIES`、`ENTITY_EDGES`、`GRAPH_*` | 核心执行 `PRODUCTION`，Dynamic/A2A/OTel 等为 `CONTROLLED`；逐项按 Graph Production Profile 验收 |
| 频道 | `/api/channels/*`、message/thread/member/action、bridge、memory candidate | `message_api.py`、`identity_api.py`、`admin_management.py` | `channels.*`；`CX_CHANNELS`、`CX_CHANNEL_MESSAGES`、成员、线程、Action Card | `PRODUCTION`；验证消息实时流式扩展、成员边界、管理命令结构化执行和审计 |
| 协作关卡 | `/api/barriers/*` | `identity_api.py`、`execution_control.py` | `barriers.*`；`CX_BARRIERS`、`CX_BARRIER_ARRIVALS`、决策记录 | `PRODUCTION`；验证到达、法定人数、拒绝、恢复和超时测试数据 |
| 审批 | `/api/approvals`、stats、approve/reject | `approval_api.py`、`governance_api.py` | `approvals.read/decide`；`APPROVAL_REQUESTS`、`APPROVAL_DECISIONS` | `PRODUCTION`；验证 N-of-M、请求人回避、重复决策与终态幂等 |
| 合规 | `/api/compliance/*`、Agent posture/profile/control/violation | `compliance_api.py`、`compliance_controller.py` | `compliance.read/propose` 及 Agent scope；`CX_AGENT_POSTURES`、`CX_COMPLIANCE_FINDINGS`、Profile/Exception/Remediation | `PRODUCTION`（提案型控制面）；验证姿态标题、三项指标含义、Finding 到 Remediation/Action Card 闭环 |
| 审计 | `/api/audit`、stats、evidence export、legal hold | `audit_api.py`、`execution_evidence.py` | `audit.read/export`；`CONTEXT_AUDIT_LOG`、evidence、retention、legal hold | Enterprise `PRODUCTION`；验证脱敏、范围、导出审批与 hold 后不可清理 |
| 用户管理 | `/api/users/*`、注册审批/Token/Policy、角色、覆盖、MFA、Session、Delegation、外部身份 | `identity_api.py`、`external_identity_api.py`、`ldap_auth_api.py`、`security_lifecycle.py` | `users.*`、`sessions.*`；`CX_HUMAN_IDENTITIES`、`CX_ROLE_TEMPLATES`、`CX_USER_ROLES`、override/MFA/session | `PRODUCTION`；验证 admin 保护、改权即失效、MFA、CSRF、只读登录和外部身份失败关闭 |
| 组织架构 | `/api/organization/*` graph/search/change/history/sync | `organization_api.py` | `organizations.*`；`CX_ORGANIZATIONS`、成员、汇报关系、变更集、历史 | `PRODUCTION`；验证中文组织/人员数据、直属关系、Agent 下属、变更审批与环检测 |
| 安全域 | `/api/security-domains/*`、成员、binding、转换草稿 | `security_domain_api.py`、`security_lifecycle.py` | `domains.manage`；`CX_SECURITY_DOMAINS`、`CX_DOMAIN_MEMBERS`、binding/draft | `PRODUCTION`；验证 Domain 隔离、成员暂停即时生效、协作组转换不隐式授权 |
| 平台配置 | `/api/platform/*`、LLM Profile、Embedding、原生 Agent、部署、路由 | `platform_capabilities.py`、`admin_management.py`、`admin_ha.py`、`platform_agent_pool.py`、`deployment_*`、`embedding_*`、`native_*`、`model_usage_api.py` | `platform.manage` 及专用动作；`CX_PLATFORM_*`、`CX_LLM_PROVIDER_PROFILES`、`CX_NATIVE_AGENTS`、部署/节点/存储对象 | 混合状态，见下一节；必须逐子页验证，不可只检查页面能打开 |

## 4. 平台配置子功能

| 子功能 | 后台实现与数据 | 状态 / 验收重点 |
|---|---|---|
| 功能开关 | `platform_capabilities.py`；`CX_PLATFORM_CAPABILITIES` | `PRODUCTION`；核心能力不可关闭，变更需原因并进入审计 |
| Graph Engineering | `graph_production_profile.py`；Graph capability/profile 表 | `CONTROLLED`；ENABLED/CONTROLLED 必须有证据引用 |
| 外部 Agent 注册 | `agent_registration.py`、Gateway 激活/Token/heartbeat | `PRODUCTION`；未知、过期、吊销、Agent ID 与数据库身份不匹配均拒绝 |
| 会话策略 | `admin_management.py`；Session policy/version | `PRODUCTION`；Dashboard/Portal 分离，空闲上限、绝对时限、Cookie 属性需在 HTTPS 验证 |
| 运行概览与管理频道 | `admin_management.py`、`platform_governance_graph.py` | `PRODUCTION`；聊天只产生建议，状态变更必须走结构化命令 |
| LLM 服务商配置 | `native_agent_api.py`；`CX_LLM_PROVIDER_PROFILES` | `PRODUCTION`；密钥加密、响应脱敏、草稿探测和引用阻断删除 |
| 模型路由与分发地址 | `model_usage_api.py`；`CX_MODEL_ROUTING_POLICIES` | `PRODUCTION`；直连与网关可并行，地址由 `CX_PUBLIC_BASE_URL` 自动产生，变更需合规原因 |
| Token 转发与计量 | `model_usage_api.py`、`model_governance_api.py`；credential/request/usage/pricing/quota/replay 表 | `PRODUCTION`；非流式和 SSE、独立凭据、硬配额/软预算、原子 reservation/settlement、AES-GCM 有界 replay；网关仍为可选路径 |
| 模型财务治理 | `model_governance_api.py`；invoice batch/line/correction、reconciliation、allocation rule/fact | Enterprise `PRODUCTION`；供应商账单幂等导入，纠正和对账追加留痕，分摊规则有效期化且事实不可变、金额平衡 |
| 外部模型证据 | `model_governance_api.py`；evidence adapter/batch | `PRODUCTION`；Ed25519 密钥轮换/吊销、sequence/nonce 重放保护、provider/Agent scope；不能自动发现未经网关且未上报的调用 |
| Admin Agent HA | `admin_ha.py`、`admin_management.py`；成员、任期、票权、Leader lease/fencing | `PRODUCTION`；验证双接入路径、多数票、Leader 更替后旧 fencing token 失效 |
| Agent Pool / 受管节点 / 共享存储 | `platform_agent_pool.py`；node/onboarding/storage/binding/endpoint | `PRODUCTION`；验证心跳、节点退役、存储探测和数据库 Endpoint 不泄露口令 |
| 升级与 Skill 分发 | `admin_management.py`、`deployment_orchestrator.py` | `PRODUCTION`；preflight、Human/Admin Agent 批准、节点 rollout、safe point、漂移记录 |
| 紧急阻断 | `containment.py`、`admin_management.py` | `PRODUCTION`；验证幂等分步结果、失败可重试、不会误当作普通 drain |
| Embedding | `embedding_governance.py`、`embedding_api.py` | `CONTROLLED`；Contract 维度/距离/预处理不可变，legacy vector 只读隔离 |
| 原生 Agent 申请与执行 | `native_agent_api.py`、`native_runtime.py` | `PRODUCTION`；Human request -> approve -> deploy -> evidence，不把 LLM 输出当作部署权限 |
| 部署目标与 Bootstrap | `deploy_api.py`、`deployment_adapters.py`、`deployment_orchestrator.py` | `PRODUCTION`；只执行清单绑定 SQL，临时身份完成交接后退休 |

## 5. 无独立管理页面但必须验收的能力

| 能力 | 入口与实现 | 核心边界 |
|---|---|---|
| 用户 Portal | `/portal/*` 经 compatibility bridge；Portal Session、会话、聊天、模型选择、Agent release | 与 Dashboard Cookie/entry 分离；LLM allowlist 和默认 Profile 服务端决定 |
| Agent Gateway | `/api/gateway/*` 与 `/api/agent-gateway/*`；`agent_gateway_api.py` | 激活凭据换短期 Token；instance、event claim/ack、heartbeat、containment、upgrade、evidence 均绑定 Agent |
| 模型 Gateway | `/api/model-gateway/completions`；`model_usage_api.py` | Browser 使用 `model_gateway.forward`；外部调用使用 `cxgw_` Bearer、`model.forward` 与 profile/agent scope；不保存 prompt/response |
| MCP | `mcp_server.py` | 只是协议适配层，仍调用同一身份、权限和领域服务，不是第二授权通道 |
| A2A | `a2a_gateway.py`、Graph A2A 映射 | `CONTROLLED`；A2A Task 映射到现有 Graph Run，不创建第二执行内核 |
| Graph Worker | graph worker/claim/heartbeat/checkpoint/complete/fail API | lease + fencing + attempt 是完成事实，Worker 声称完成不等于验收通过 |
| 事件总线 | `event_bus.py`、Graph inbox/outbox/dead-letter | 至少一次投递，消费方必须幂等；死信和积压必须可观测 |

### UI 交互边界补充

- 实体关系视图由 `shared/web/src/pages/GraphPage.tsx` 渲染节点和拓扑连线，
  不显示难以阅读的边关系文字，也不重复渲染关系明细表。
- 用户管理的有效访问模拟由 `UsersPage` 调用
  `/api/users/{principal_id}/access?action={action}`。前端动作选择器只是
  只读诊断入口，一次评估一个动作；服务端仍以数据库角色、组织、安全域、
  委派和显式拒绝为最终事实源，模拟不会修改授权。
| 执行证据 | `execution_evidence.py`、`graph_assurance.py` | 哈希、来源、签名/扫描状态和 stale 传播；Evidence 不是权限 |
| 配置加密 | `connection_crypto.py` | Provider/DB/API secret 仅以密文或引用保存，日志和支持包必须脱敏 |
| 离线六包 | `build.py` | Oracle/PG/YashanDB x Community/Enterprise；构建期替换 adapter 并执行 edition allowlist |
| 部署与回滚 | `migration_runner.py`、各 adapter `deploy/baseline_v4_4_10.json` | v4.4.10 全新部署、journal/checksum、preflight、终止迁移 58；历史脚本用于审计复现，不承诺旧包原地升级 |
| 运维支持 | readiness、日志、recovery/POC/deployment 文档 | 应配置 HTTPS、反向代理、持久化日志、备份恢复和探针阈值 |

## 6. 三数据库安全实现矩阵

| 边界 | Oracle | PostgreSQL | YashanDB |
|---|---|---|---|
| Schema Owner / Agent 分离 | Schema Owner + Agent End User/Data Grant | Schema Owner pool + Agent LOGIN role | Schema Owner + Agent 用户/对象授权 |
| 运行身份 | Session context / 包校验 | `app.current_agent_id` + `public.current_agent_identity()` | Session context / 包校验 |
| 行级隔离 | VPD/安全包与服务端 scope | RLS + FORCE RLS +服务端 scope | Oracle-compatible policy/package + 服务端 scope |
| v4.4.10 模型表 | `55_v4_4_10_model_usage_wallboard.sql` + `56_v4_4_10_runtime_repair.sql` | 55 建表、56 修复 management/Agent RLS | 55 建表、56 补齐 request/routing 唯一约束 |
| 参数化 SQL | `:name` adapter bind | facade 将 `:name` 转换为 psycopg bind | `:name` adapter bind |
| 时间/分页差异 | `INTERVAL '5' MINUTE`、`FETCH FIRST` | `INTERVAL '5 minutes'`、`FETCH FIRST` | Oracle-compatible interval、`FETCH FIRST` |
| 必测负例 | Agent 不能取得 Schema Owner secret | 伪造 `app.current_agent_id` 不得绕过绑定角色；凭据表不能由 Agent 读 | Agent 用户不能访问未授权对象或跨域数据 |

PostgreSQL v4.4.10 已修复先前错误引用的 `app.current_principal_id`。模型凭据和路由仅允许管理连接；Agent 运行连接只可读写 actor/agent 为自身的 request/usage。应用管理连接仍必须经过 FastAPI 的 Session、CSRF、action 和数据 scope，不能把数据库 Owner 连接暴露给 Agent。旧协作兼容路由现在还必须通过 `assert_execution_group_access()`，数据库 Owner 连接不能绕过安全域绑定和当前成员检查。

## 7. v4.4.10 当前审计结论

### 已在本轮修正

1. `/api/wallboard`、`/api/model-usage/summary` 改用 `wallboard.read`、`model_usage.read`，不再错误依赖 `agents.read`。
2. 管理大屏的 Agent、Session、Task Plan、Loop、stalled、Native Agent 和模型用量改为同一个授权 Agent 集合；scope 解析失败时关闭结果而不是扩大范围。
3. 新增 `/ready` 与 `/api/ready`，数据库或 v4.4.10 控制面迁移不完整时返回 503；`/health` 保持纯 liveness。
4. 模型转发与报表权限分离：浏览器需 `model_gateway.forward`；外部转发使用独立 `cxgw_` Bearer，不再借用 Dashboard Session。
5. Gateway Credential 现在校验 `ACTIVE`、过期时间、`model.forward`、`profile:<id>` 和 `agent:<id>` scope；吊销后立即失效。
6. 重复幂等键在调用 Provider 前返回稳定 409，且相同键不能替换为另一输入摘要，避免数据库唯一约束泄露为 500。
7. PostgreSQL v4.4.10 RLS 改用项目真实运行身份函数，并补齐 credential policy；YashanDB 补齐 request/routing 唯一约束。
8. `AUDITOR` 默认模板获得 Security Domain 范围的 `wallboard.read` 和 `model_usage.read`；不向普通用户授予管理大屏或报表权限。
9. Legacy `/api/collab` 不再直接查询全部协作组；通过 `execution-group-scope/v1` 返回当前安全域内的兼容执行组，分支、计划、上下文和 Loop 操作统一重新验证安全域绑定与执行组成员关系。

### v4.4.10 最终缺口处置

| 编号 | 缺口 | 当前状态 | 决策 |
|---|---|---|---|
| G-01 | Gateway 硬/软 Token 与金额配额 | `CLOSED` | 版本化策略、原子 reserve/settle/release/expiry、硬拒绝前置、软告警继续执行、聚合 status 已实现 |
| G-02 | 幂等请求完整响应重放 | `CLOSED` | 非流式成功响应以 AES-GCM 有界快照保存；快照与成功状态同事务，重复请求不再分发 Provider |
| G-03 | Wallboard Definition 生命周期 | `CLOSED` | allowlist widget/dimension、不可变版本、publish/rollback 事实和按 definition 授权投影已实现 |
| G-04 | 发票对账与内部 chargeback | `CLOSED` | 幂等账单、追加纠正/对账、有效期规则和不可变平衡分摊已实现；Community 明确拒绝 Enterprise chargeback |
| G-05 | 网关之外的模型调用自动探知 | `ACCEPTED PHYSICAL BOUNDARY` | 平台不声称自动发现绕行流量；只有网关事实或可信 Ed25519 adapter evidence 计入 observed，其他保持 unknown |
| G-06 | 公开 correlation/retryability contract | `CLOSED` | v4.4.10 HTTP 错误统一返回 `code/message/correlation_id/retryable` 并带匹配的 `X-Correlation-ID` |
| G-07 | 性能证据 | `BOUNDED EVIDENCE` | `v410_full_flow_gate.py` 与 `v410_model_governance_benchmark.py` 记录三库当前数据量、Provider 基线/网关附加延迟、SSE 首包、配额并发、大屏 P50/P95/载荷；目标容量仍须现场认证 |
| G-08 | migration 55/56/57 现场闭包 | `CLOSED` | 三库已生成 pre-57 逻辑恢复点并完成 55/56/57 journal、对象闭包与 PG FORCE RLS 验证；不得修改历史 checksum |
| G-09 | 协作组授权收敛 | `CLOSED` | 协作组保留为执行记录；外部兼容读取与执行操作必须通过安全域绑定、当前成员和 Agent 执行组成员检查 |

## 8. 全流程验收顺序

1. **主机与运行时**：确认 Linuxbrew Python `/home/linuxbrew/.linuxbrew/bin/python3.14`、Node 构建产物、时区、文件权限、日志目录和磁盘容量。
2. **数据库预检**：分别用 Schema Owner 和最小权限 Agent 身份连接；检查版本、字符集/时区、连接池上限、迁移 journal 和 v4.4.10 的 55/56/57 三个步骤。
3. **秘密与网络**：通过受控 `CX_CONFIG_PATH` 注入数据库密码；设置 `CX_PUBLIC_BASE_URL=https://实际域名`、Secure Cookie、TLS、可信反向代理和出口 Provider allowlist。
4. **探针与流量入口**：进程启动后 `/health` 必须 200；数据库不可用时 `/ready` 必须 503，恢复后自动回到 200；入口只转发 HTTPS，并保留 `X-Correlation-ID`。
5. **身份负例**：验证错误密码、锁定、MFA、CSRF、Session 超时、改权踢出、Dashboard/Portal Cookie 隔离、只读账号不能 mutation。
6. **数据范围负例**：准备两个组织和两个 Security Domain；Manager/Auditor 只能看到本范围 Agent、用量、审计和大屏聚合。
7. **Agent 全流程**：Enrollment -> redeem -> activate -> Token -> instance -> heartbeat -> event claim/ack -> evidence -> revoke/offboard；每一步做过期/伪造负例。
8. **业务全流程**：Task、Workspace、Knowledge、Memory、Skill、Spec、Branch、Loop、Graph、Channel、Barrier、Approval、Compliance、Audit 逐页面执行一条成功与一条拒绝路径。
9. **模型全流程**：Provider Profile save/probe -> 直连/网关并行路由 -> `cxgw_` scope -> 非流式/SSE/replay -> quota -> usage/pricing -> invoice/reconciliation/correction/allocation -> signed evidence/revoke；确认数据库无 prompt、response、明文 key。
10. **管理面全流程**：Admin Agent admission/HA、节点、共享存储、升级 preflight/approval/rollout、Skill safe point、containment 与 recovery。
11. **性能与故障**：至少覆盖 10 万 usage、1 万 Agent/Session 历史、并发大屏刷新、Provider 超时、SSE 中断、连接池耗尽、数据库短暂重启、Worker lease 过期和死信积压。
12. **备份恢复**：在隔离环境恢复数据库和密钥引用，确认已吊销凭据不会复活、迁移 journal 未丢失、审计/evidence 哈希保持一致。

## 9. 发布验证命令与证据

```bash
openspec validate --all --strict
/home/linuxbrew/.linuxbrew/bin/python3.14 -m pytest -q
cd shared/web && npm run build
cd /root/ai-agent-infra
git diff --check
/home/linuxbrew/.linuxbrew/bin/python3.14 build.py \
  --version 4.4.10 --profile production \
  --output-root build_output/v4.4.10
```

六包构建后分别验证包内没有另一数据库 adapter、Community 没有 Enterprise 模块、版本占位符已替换、迁移 55/56/57 存在、文档包含本总账。实时数据库证据应记录在部署验收报告中，不把测试账号口令、DSN、Provider key、Gateway token 或 prompt 写入仓库。

## 10. 后续版本优先级

1. v4.4.10 补丁只处理阻断、安全错误和三库不一致，不扩张新执行内核。
2. 下一版本不得绕过现有 quota/replay/finance/evidence/definition 事实表另建计费或大屏旁路。
3. G-05 的物理边界保持不变：没有网关或可信签名 adapter 的调用只能标为 unknown，不能由统计推断成“已覆盖”。
4. 容量认证必须以三库同一数据规模、同一授权 scope、同一刷新周期重跑性能工具；本地有界数据不替代客户容量结论。
