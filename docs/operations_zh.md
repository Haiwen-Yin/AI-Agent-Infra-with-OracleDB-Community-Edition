# 川序 v4.4.15 运维与技术说明（中文）

本文说明当前发行包的部署、迁移、恢复、权限、模型和验收操作。下面的中文步骤可以独立阅读；文末英文资料仅用于补充接口和历史实现参考。工作交接、上下文、候选审核与 Skill 客户端另有[完整中文操作手册](continuity-operations_zh.md)。

## 部署

先选择一种数据库及 Community / Enterprise 发行版。三数据库不能混用安装包、迁移 SQL 或驱动。Oracle 使用独立 PDB，禁止部署到 CDB 根；YashanDB 同样使用独立 PDB；PostgreSQL 使用独立数据库和 Owner。已使用的基线库、系统库和业务库不能当成“空测试库”初始化。

DBA 负责创建并打开目标 PDB/数据库、表空间和独立 Owner，准备备份、网络及必要扩展。平台初始化不会隐式创建数据库集群、修改防火墙或替代 DBA 授权。

| 数据库 | 初始化前核对 |
| --- | --- |
| Oracle AI Database 26ai | 字符集 AL32UTF8、Partitioning、有效 Oracle Text、有限表空间配额及包内 `0_oracle_database_prerequisites.sql` 要求。Enterprise 还要具备 End User、DATA ROLE、DATA GRANT 与会话角色的完整前置。使用 Thin 客户端时须匹配数据库传输加密策略，不能关闭加密来绕过连接失败。 |
| PostgreSQL 18 | 已授权环境当前实测 18.6；核对 `0_pg_database_prerequisites.sql` 中的角色管理、AGE、向量和作业扩展前置。Owner 与每个 Agent 的 LOGIN 角色分开，强制行级安全不能由普通 Agent 绕过。 |
| YashanDB 23.5.4+ | DSN 指向正确 PDB，确认独立用户、对象授权、字符集、表空间和包内前置脚本；使用匹配服务端的原生客户端与 yaspy。不能复制 Oracle 专用语法或错误码处理。 |

在可信目录解压安装包，并核验取得的 SHA-256；需要签名验证时按[中文发布签名说明](release-signing_zh.md)使用独立取得的公钥。安装 Python 3.14+，从包根目录执行：

```bash
bash scripts/install_offline.sh
bash scripts/config_wizard.sh
```

离线安装使用包内已校验的 vendor 依赖并创建本包 `.venv`，不要求向系统 Python 全局安装依赖。配置向导填写数据库目标、Web 监听地址和端口、模型与 Embedding 配置；端口必须为 1–65535。外部可访问性还取决于反向代理、防火墙和路由。

首次初始化不需要外部 Agent 或真实模型，由确定性的 Bootstrap Deployment Agent 执行。以下以 PostgreSQL Community 为例；其他版本将两个参数改为对应的 `oracle` / `yashandb` 和 `community` / `enterprise`：

```bash
bash scripts/install_platform.sh initialize --version 4.4.15 \
  --database pg --edition community --config config.json
bash start_web_server.sh start
```

初始化会核对空目标、前置能力、逐步迁移及基线清单，交互输入初始管理员密码，建立 Human 管理员和平台原生管理 Agent，完成后退休临时部署身份。初始密码至少 12 位，包内没有通用默认密码。失败或中断时先查看部署状态和账本，通过同一部署入口恢复，不能手工跳过失败步骤或把未知结构认作空库。

`config.json` 与加密主密钥应仅由运行用户读取，并纳入客户秘密管理；保留 `~/.ai-agent-infra/master.key`，不能另外生成不匹配的密钥来“修复”解密失败。Runtime / Business Agent 配置只包含各自独立凭据，不能携带 Owner 后备密码。

启动后核对 `/api/health` 的进程与版本、`/api/ready` 的数据库就绪状态，以及管理页面中的数据库治理配置。健康响应、启动模式为 production、功能配置正常是不同检查，任何单项都不代表完成发布验收。需要再次核验部署时运行：

```bash
bash scripts/install_platform.sh verify --version 4.4.15 \
  --database pg --edition community --config config.json
```

代理后的外部域名用 `CX_PUBLIC_BASE_URL=https://platform.example.com` 配置；模型转发地址由平台生成，不能填写任意第三方中转地址。服务停止使用包内 `start_web_server.sh stop`，先确认正在运行的目录、端口和进程，避免误停其他实例。

详细说明：[deployment.md](deployment.md)。

## 升级与迁移

v4.4.14 已正常发布，基线终点为 82；v4.4.15 的三数据库终点均为 97。以所选发行包唯一的 `scripts/deploy/baseline_v*.json` 为部署合同，不根据历史模板文件名猜测终点。

升级前完成数据库原生备份和恢复演练，记录目标、已有迁移校验和、运行目录与进程。已有数据不得重新执行空库初始化。先运行包内迁移预检，再通过受约束部署入口确认并按账本顺序执行；预检失败时保留日志并修复原因，不清空目标库掩盖问题。

迁移 85 修复任务状态和步骤关联；86–88 添加关系化工作交接和原生执行关联；89–93 保护动态 MCP 工具发现与派发来源；94 保存逐修订并行交接策略；95–96 绑定上下文 Worker 和原始 Gateway 凭据；97 保存原生来源快照。已应用 SQL 和结构清单不可修改校验和。后继迁移不能在未 APPLIED 时替代旧结构验证。

Oracle 任务迁移采用可恢复复制及校验，只在最终切换时排空涉及的任务写入；不要把它扩大为整个平台停写。交接策略回填与上下文 Worker 升级同样只排空相应旧写入进程。切换后先完成严格结构、历史依赖、权限和运行就绪检查，再恢复流量。失败保留旧目录和账本，按已记录的恢复阶段继续，禁止直接强杀全部服务。

详细说明：[migration.md](migration.md)。

## 恢复与隔离

运行状态、租约、围栏令牌、任务、检查点和审计记录以数据库为准。进程重启只回收
本节点已经过期的租约；旧 Worker 不能提交过期围栏令牌。数据库不可用时停止新的
副作用，不使用内存状态绕过授权。数据库复制、备份、主备切换、RPO/RTO 由部署方负责。

上下文模型请求的结果不确定时记录 UNOBSERVED，不自动再次发送。原始 Gateway 凭据已撤销时，新令牌不能替代原凭据继续旧请求。工作、交接、审核和输入回执保留数据库历史；权限撤销或来源删除会阻止后续读取，但不删除审计事实。

### 运行隔离

Web 控制面能运行与主机能安全承载不可信 Agent 是两种准入。强隔离要求独立 UID/GID、工作目录、namespace、cgroup v2、seccomp、只读根文件系统、最小能力和受保护的 Host Manager；具体镜像、内核、系统策略与补丁必须通过包内主机门禁。发行依赖要求 glibc 2.34+ 及对应支持的 Linux 基线，旧 RHEL/Oracle Linux 8 环境不能按当前包支持。

外部 Agent 绕过受管运行器时不能声称进程已隔离或已终止。协作式 Skill 客户端通过共享进程锁保护运行中的回合，在独占安全点原子切换，保留旧文件；它不能约束绕过客户端的独立后台进程。配置数据库权限不能替代主机隔离证据。

补充参考：[recovery.md](recovery.md)、[runtime-isolation.md](runtime-isolation.md)、[linux-platform-compatibility.md](linux-platform-compatibility.md)。

## 安全与权限

Human、平台 Agent、外部 Agent 和 Schema Owner 使用不同身份。凭据失效时不能回退到
部署账户；知识按公司公开、组织子树、组织级和 Human/Agent 私有范围过滤。安全域是
协作授权边界，频道只承载消息，不扩大数据权限。Enterprise 审批、审计和应急控制由
服务端与数据库共同执行。

详细说明：[security.md](security.md)、[minimum-privileges.md](minimum-privileges.md)。

## 模型、MCP 与 A2A

模型及外部工具的治理姿态区分 `OFF`、`READ_ONLY`、`PROPOSAL_ONLY` 或 `GOVERNED_EXECUTOR`。MCP 连续性客户端通过已认证 Gateway 操作；动态工具必须逐项显式开放，调用时仍须当前授权。标准 A2A 互操作能力保持禁用。模型生成的写入、策略变更、Agent 控制、外部联系和发布默认只能形成提案。
供应商证据记录模型身份、校验、工具调用、用量、延迟、超时、取消、重试和完成状态，
不保存隐藏推理内容或完整提示词。未被网关观测的直连流量不能报告为零消耗。

模型服务商配置需要地址、模型 ID 和适用范围；服务允许无密钥调用时，空 API Key 不应阻止请求。保存后的健康状态要求真实返回匹配模型的有效回答，仅能访问服务地址不算通过。Portal、原生活跃 Agent 或待处理申请仍引用的模型配置不能直接退休。网关可选，按配置选择直连、网关或两者并存；网关只计量实际经过且可观测的请求。

Portal 知识增强回答按用户与 Agent 双方授权过滤来源；没有可用知识时是否调用通用模型由策略决定，没有模型时可返回授权摘录。引用、无知识和模型不可用要明确区分。频道中通过英文显示名显式 @ 平台管理 Agent；Enterprise 还提供独立的合规 Agent。受控命令只执行当前获准操作，管理 Agent 不能借 Human 管理员或 Owner 身份扩大权限。

详细说明：[model-usage-and-wallboard.md](model-usage-and-wallboard.md)、[api-reference.md](api-reference.md)。

## 图、组织与 DB4A2A

Graph Runtime 的运行、租约、检查点和事件是数据库事实；图只是授权后的投影。DB4A2A
传递受版本、摘要和范围约束的上下文引用，接收 Agent 仍须独立认证授权，不代表标准
A2A 互操作。

组织用于表达人员、Agent 的责任和知识范围，安全域用于协作授权，频道用于沟通。调整组织或成员关系后重新检查当前权限，不能让图中的边或旧协作组代替授权。Graph Runtime 核心与授权检查可用；清单草稿导入、只读 SLO 和检查点分叉为受控能力；动态图迁移、框架适配器执行、Replay、A2A 和 OTLP 的禁用状态不能由提示词或 Skill 自动改变。

### 实体化架构

Principal、组织、安全域、任务、步骤、执行、工作契约、交接、修订、来源、候选、审核、发布和诊断分别拥有明确实体与关系。正文用于承载内容，不能把责任、类型、状态和授权全部塞入无类型 JSON。事务负责状态与审计的一致提交，唯一键、外键和不可变历史约束负责并发及追溯。原生资源关联使用稳定标识，不将可变任务状态作为来源身份。

详细说明：[graph-engineering.md](graph-engineering.md)、[organization-governance.md](organization-governance.md)、
[db4a2a.md](db4a2a.md)。

## 发布判断

当前版本的源码、发行包、数据库、UI、依赖、POC 和支持包证据统一记录在
`release_evidence/manifest.json`；只有对应版本的清单明确可发布、状态为 `PASS` 或 `PASS_WITH_CONSTRAINED_CLAIMS`，且六个包的哈希与验收记录一致，才能按其中声明的边界交付。后一状态中的限制需要明确保留，不能扩大为客户容量、任意主机隔离或数据库集群高可用承诺。测试库应记录为临时目标；清理时保留基线、系统数据库与明确受保护的 TEST PDB。
