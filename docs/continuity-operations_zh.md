# 工作交接与上下文连续性操作 v4.4.16

[English](continuity-operations.md)

Dashboard 与 Portal 共用的诊断面板展示来源能力及实际取得的数据库服务端版本元数据。如果当前权限无法读取版本，明确显示不可用，不扩大数据库权限。表单还可检查指定实例、组装输入回执或 Skill 分发；没有独立证据时，跨入口一致性保持未观测。Worker 失败保留 `LLM_REQUEST_TIMEOUT`、`LLM_EMPTY_RESPONSE`、`LLM_HTTP_503` 等有界分类，不在失败原因中写入提供方正文或凭据。

## Skill 安装与协作式运行切换

Linux Agent 如明确使用受管执行包装器，可运行：
`python scripts/tools/skill_runtime.py --root <专用私有运行目录> --public-key-file <运维固定公钥文件> sync --upgrade-id <已分配升级标识> --database <oracle|pg|yashandb> --edition <community|enterprise>`。
通过 Agent 私有环境配置 `CX_AGENT_GATEWAY_URL`（以 `/api/agent-gateway` 为基础路径）、`AI_AGENT_ID`、`CX_AGENT_INSTANCE_ID`、`CX_AGENT_ACCESS_TOKEN`。公钥是独立受信的 URL-safe Base64 Ed25519 公钥，不从下载包中获取。

客户端下载指定接收者的签名包，验证全部内容后，在专用私有目录安装普通文件，并在切换前重新检查服务端当前信任。接收确认与激活确认分开执行。存在活动的受管执行时返回 `RUNTIME_BUSY`，应等执行结束后重试。活动指针原子替换，只会指向完整安装；旧版本保留，不自动清理或回滚。最终确认失败时返回 `LOCAL_ACTIVE_SERVER_ACK_PENDING`，重复同一同步命令即可按本地精确版本与服务端协调。

每次完整 Agent 执行使用：
`python scripts/tools/skill_runtime.py --root <专用私有运行目录> --public-key-file <运维固定公钥文件> run -- <Agent 命令>`。
该命令必须读取 `CX_ACTIVE_SKILL_PATH`，并在当前进程生命周期内完成执行，不脱离包装器启动后台运行时。读锁由启动的进程继承，因此包装器异常退出不会提前解锁仍在运行的任务。`status` 会验证本地已安装内容并返回版本摘要。验证会读取保留的完整压缩包与已安装文件；每个保留版本均需预留压缩包及解压文件的空间。

此适配器协调主动接入的本地进程，不隔离绕过它的进程。本地观测标记为 `LOCAL_COOPERATIVE_RUNTIME`；服务端无法独立观测任意外部进程的切换，因此外部 Skill 激活诊断仍保留 `UNOBSERVED`。

外部 Agent 可以通过公开令牌交换接口申请 `workspaces.read` 和 `workspaces.write`
范围，分别用于连续性读取与写入；申请范围不授予安全域或资源权限。签名升级包与 Skill
包的准备方法见[发布签名说明](release-signing_zh.md)。

## 安装与授权

迁移 95、96 新增三张不可变关系表，分别记录原生执行与组装上下文的关联、输入尝试与 Worker 认领信息，以及发起请求的原始 Gateway 凭据。安装时保留 SQL 与结构清单，在启用支持上下文的 Worker 前完成两项迁移。

Dashboard 的 `POST /api/context/runtime-executions`、Portal 的 `POST /portal/api/continuity/context/runtime-executions` 和 Agent 的 `POST /api/agent-gateway/continuity/context/runtime-executions` 在同一事务内组装上下文并创建原生 Agent 执行请求。MCP/命令行操作名为 `context_runtime_enqueue`。请求包含 `agent_id`、`messages`、`context` 组装参数、`reason` 和 `idempotency_key`。发起者需要当前安全域内的工作区写入权限与 `agents.operate` 权限；目标 Agent 必须激活且有权读取该域和全部来源。Gateway 令牌还需要 `agents.operate` 范围。

入队回执只代表等待执行，不代表模型已完成。Worker 在发送前再次验证权限、原始凭据、实例及自身租约，并记录真实输入关联。原凭据被撤销或过期后，签发新令牌不能恢复旧请求。Worker 中断导致发送结果不确定时，记录为 `UNOBSERVED`，不自动重发。

Dashboard 和 Portal 的工作交接页面共用“使用上下文执行”表单：加载可执行的原生 Agent，选择目标，填写任务与用途，再提交并刷新结果。当前工作及明确填写的来源组成有效期 15 分钟的上下文。发送前和读取结果时，发起者与目标 Agent 均需保留全部来源的读取权限；上下文过期后结果也不可读取。结果接口为 `GET .../context/runtime-executions/{execution_id}`，Agent 分页列表为 `GET .../context/runtime-agents?security_domain_id=...`，对应 MCP/命令行操作为 `context_runtime_read` 和 `context_runtime_agents`。

当前实现通过迁移 86 至 88 建立 45 张关系实体表。安装时需要执行与发布版本绑定的完整迁移链，并保留 `86_v4_4_15_continuity_entities.schema.json`、`87_v4_4_15_continuity_bindings.schema.json` 和 `88_v4_4_15_execution_links.schema.json` 结构校验清单。部署校验会检查列、默认值、约束、不可变历史触发器和数据库原生授权；迁移账本中的 APPLIED 状态不能单独证明结构正确。

当前 v4.4.16 的部署终点为三种数据库的迁移 97。迁移 89 至 93 补充动态 MCP 工具授权保护，不改变上述连续性实体表数量。在工具详情中，具备权限的操作人员可以明确开放或撤销一个活动工具，并填写原因。独立 Agent 只能通过只读视图 CX_MCP_EXPOSED_TOOLS 发现已开放且活动的工具契约；不能通过原生 SQL 开放工具、修改或删除已开放的契约。重新导入或刷新工具会关闭其开放状态，等待重新授权。即使客户端缓存了工具名称，调用入队前也必须重新检查开放状态；工具可见不代表执行已获审批。

迁移 97 新增七张有明确类型的不可变实体表，保存原生来源的精确快照。工作连续性页面可以固定 TASK（任务计划与步骤）、GRAPH（运行与节点进度）、DB4A2A（派发契约）或 AUDIT（调用者本人的安全事件摘要），并将返回的版本引用加入所选来源。快照包含 UTC 采集时间与摘要，不代表原生执行仍处于该状态。后续读取仍检查原始对象是否存在、责任人和当前权限；删除、责任转移或撤权会阻止读取，但不会抹去历史。快照仅限原安全域，不包含任意工作区正文或企业审计详情。单次最多包含 1000 条子记录，含元数据的总大小不超过 256 KiB。

HTTP 使用各入口相同前缀下的 `POST .../context/native-sources`，提交 `family`、`entity_id`、`security_domain_id`、`reason`、`idempotency_key`；MCP/CLI 操作为 `context_native_capture`。调用者需要工作区写入及原始来源读取权限；DB4A2A 还要求是发送方或接收方，AUDIT 还要求安全事件属于本人且具备 `audit.read`。持有版本引用不会自动授予目标 Agent 使用来源的权限。

迁移 94 新增不可变的 `CX_WORK_HANDOFF_POLICIES` 关系表，连续性实体表总数增至 46 张。请同时保留该迁移的 SQL 和结构清单。每个工作修订都有对应策略，已有历史修订回填为单接收者串行策略。只有迁移 94 的精确校验和与 APPLIED 记录均验证通过，迁移 86 才采用后继清单校验已移除的串行唯一约束。

如果已记账的迁移 94 执行中断，部署程序会先恢复该精确迁移，再检查旧约束；前提是迁移 85 至 93 均有匹配校验和的 APPLIED 记录（92 仅用于 YashanDB）。恢复后仍重新验证完整迁移链。脚本发生变化或前置步骤不完整时，恢复会被阻止。策略回填后不能继续运行旧版连续性写入程序，因为旧程序不会为新工作修订写入策略。切换运行服务时，需要先排空这类写入，并在启用替换服务前检查策略覆盖完整性。

Agent 数据库账号不能直接读写这些控制面实体表。请通过经过认证的 HTTP Gateway、MCP 工具或命令行操作。每次请求都会重新检查当前主体、安全域和资源权限；Gateway 同时检查实例租约、令牌范围、撤销状态和 fencing token。安全域恢复后，隔离期间撤销的凭据不会自动恢复。

Dashboard HTTP 使用现有会话和 CSRF 校验。Portal 页面使用自己的会话，通过 `/portal/api/continuity` 调用同一业务服务；写入还必须通过当前页面租约校验，不能借用 Dashboard 会话或其他页面的租约。Agent 路由的统一前缀为 `/api/agent-gateway/continuity`。知道记录标识、获得来源引用或持有其他参与者的标识，都不会额外赋予读取权限。

## 串行与并行交接

在 Dashboard 或 Portal 的“交接策略”中，当前工作责任人可填写 1 至 16 的最大活动接收者数及变更原因。设为 1 时，确认接收后转移工作责任；设为 2 至 16 时，协调者保留工作责任，多名接收者独立确认、开始执行并提交结果。提交“已完成”结果前必须先开始执行。同一接收者不能重复拥有活动交接。变更策略前，需要先完成、拒绝、取消或等待所有活动交接过期；每次策略变更创建新的不可变工作修订。

HTTP 接口为 `POST /api/work-contracts/{work_id}/handoff-policy`；Portal 与 Agent Gateway 使用各自现有连续性前缀。MCP／命令行操作 `work_handoff_policy` 的 `request` 包含 `work_id`、`expected_version`、`max_active_recipients`、`reason` 和 `idempotency_key`。操作仍检查当前责任人、安全域及资源权限。版本过期或存在活动交接时返回冲突。读取历史工作修订可查看当时的策略。

## 配置 Agent 客户端

动态 MCP 调用需要提供安全域、arguments 参数对象、操作原因和幂等键，并使用与连续性操作相同的实例绑定 Gateway 配置。Bearer 需要 actions.propose 范围；Agent 还必须具备该域内当前的工作区读取、工具读取和操作提议权限。迁移 93 新增一张不可变工具请求关系表，关联现有执行队列；提交后仍为 WAITING_APPROVAL，不会自动执行。Worker 派发前重新检查自身租约、原 Agent 凭据与实例、当前域权限、开放状态、契约摘要及排队载荷摘要。凭据过期或撤销后，需要重新授权并提出新请求，后续审批不会自动恢复旧请求的权限。

通过现有私有运行配置提供下列环境变量。不要将密钥写进命令参数或项目文件。

| 环境变量 | 说明 |
| --- | --- |
| `AI_AGENT_ID` | 已注册的 Agent 标识；未设置时读取 `MCP_AGENT_ID` |
| `CX_CONTINUITY_GATEWAY_URL` | 完整 Gateway 分组地址，例如 `http://127.0.0.1:8000/api/agent-gateway/continuity` |
| `CX_AGENT_INSTANCE_ID` | 属于该 Agent 的当前有效实例标识 |
| `CX_AGENT_ACCESS_TOKEN` | 绑定当前实例、具备所需工作区权限范围的 Gateway 访问令牌 |

MCP 还需要在 `AI_AGENT_TOKEN`（或 `MCP_AGENT_TOKEN`）中提供现有注册凭据，并在 `mcp.exposed_tools` 中启用 `continuity`。注册凭据与 Gateway 访问令牌是两类不同凭据，不能互换。已有配置如果明确列出开放工具，需要显式加入 `continuity`。MCP 工具使用下文的结构化操作请求，禁止通过参数替换调用主体或 Gateway 地址。

## 命令行检查

在生成的软件包目录中，使用该安装的 Python 环境执行：

```bash
.venv/bin/python scripts/continuity.py setup --domain DOMAIN_ID
.venv/bin/python scripts/continuity.py doctor --domain DOMAIN_ID
.venv/bin/python scripts/continuity.py capabilities --domain DOMAIN_ID
.venv/bin/python scripts/continuity.py verify-context --domain DOMAIN_ID --assembly-id ASSEMBLY_ID --purpose "验证上下文实际输入"
```

`setup` 验证已有配置能否通过服务端身份、安全域、数据库和实例检查，并将诊断结果持久化；该命令不会创建身份、授予权限或保存凭据。`doctor` 还请求检查入口一致性；在没有集成观测结果时，这一项保持 UNOBSERVED（未观测）。`capabilities` 返回当前主体在指定安全域中可查询的操作契约，并将运行验证状态单独列出。它不代表数据库引擎版本已完成认证，也不表示所有操作都健康。

`verify-context` 必须提供上下文组装标识或 `--sources-file`，也可以同时提供。来源文件是 JSON 数组，每个引用包含 `family`、`entity_id`、`revision_id`、`content_digest`。服务端按指定用途重新授权每一个精确来源。只有存在内容摘要和条目数一致、已完成的模型输入回执，才确认上下文实际送达；仅完成组装会返回未观测。

诊断命令只有在 PASS（通过）时退出码为 0。FAIL（失败）、UNAVAILABLE（不可用）和 UNOBSERVED（未观测）均以退出码 1 返回，并在 JSON 中保留具体状态。客户端错误只返回经过脱敏的错误码，不输出远端数据库错误明细。客户端不会跟随重定向，也不会在发送结果不确定时自动重试。

## 结构化操作

使用 `call --request-file request.json` 读取操作请求，或将 JSON 通过标准输入传给 `call`。例如，读取工作契约的第 2 个修订：

```json
{"operation":"work_read","request":{"work_id":"WORK_ID","revision":2}}
```

操作覆盖工作契约创建、修订和状态变更；交接发起、读取、修订和确认；结果提交与读取；上下文组装与读取；四类候选创建、修订、审核和提升；正式对象退休；显式发布、撤回和诊断。经过认证的能力查询会列出操作名称，MCP 工具发现会提供完整的参数结构。写操作需要原因和幂等键；涉及版本更新的操作还需要预期版本。同一幂等键不得提交不同内容，否则返回冲突。

## 当前交付边界

Dashboard 工作区提供“工作交接”视图；Portal 顶栏的“工作交接”进入 `/portal/continuity`，两者复用相同表单与服务端授权。页面支持创建和修订工作契约、发起和处理交接、提交执行结果、显式提议经验候选，以及运行持久化诊断。安全域和接收者选择按当前工作区权限与域成员关系查询，不额外要求频道权限。列表采用分页，只返回元数据，不泄露来源正文。

工作和交接历史采用独立只读预览，不替换当前编辑对象。发送者可以修订尚未被接收且未过期的交接；表单展示将关联的工作修订及验收条件，提交时同时校验已读取的工作版本、交接版本与正文修订。并发变化返回冲突，不能静默使用提交时才读取的新工作版本。

“候选审核与正式版本”提供记忆、知识、经验、技能四类结构化表单。每项来源需要实体标识、精确版本和 SHA-256 摘要；可显式指定被替换的正式版本。保存后保持待审核。提议者可修订待审核候选，独立审核者按已读取版本和摘要通过或拒绝，然后显式生成正式版本。提议者不能审核或提升自己的候选。历史预览保持只读，生成结果展示正式实体及版本标识。候选列表只向提议者或当前具备相应类型审核权限的域管理员返回元数据，实际正文读取仍重新校验每项来源。

交接证据固定原始发布授权。原授权撤回后，不能用等价的新授权替代。绑定接收实例的操作会检查实际 Gateway 令牌中的实例与 fencing token；实例替换保留同一个 Agent 主体的责任链。凭据使用历史仅保存令牌摘要。

创建工作契约时可选填 `workspace_id`、`task_id`、`graph_run_id`。独立的不可变关系记录保存类型、原生资源标识和原责任主体，并通过外键关联工作契约及主体。使用时重新检查原资源权限和当前域成员关系；任务状态不进入关联键，因此状态变化不会被关联记录阻塞。原资源删除、撤权或责任主体改变后，关联停止被使用，历史仍保留。关联本身不是任务或图运行正文的历史快照，不能代替后续精确来源解析。

`outcome_propose_experience` 需要提供读取结果时取得的 `expected_outcome_id` 和 `expected_digest`、结构化经验提案、原因及幂等键。操作创建 PENDING（待审核）候选，并固定 HANDOFF_OUTCOME 精确来源，不会自动提升为正式知识。独立审核者必须同时具备当前结果及其证据的读取权限。结果来源限于原安全域及交接参与者，暂不支持跨域发布。

精确来源包括 Memory、Handoff、Handoff Outcome，以及经候选审核提升流程产生的 Knowledge、Experience、Skill。Task、Graph、DB4A2A 和本人安全事件通过迁移 97 的原生快照固定版本；使用前先执行显式采集，不能将当前状态当作历史版本。工作执行与原始 Gateway 凭据、来源权限交集和输入回执关联。并行交接策略、Dashboard / Portal、HTTP / MCP / CLI 和协作式 Skill 客户端均属于本版交付范围。能力查询不等于对所有记录拥有操作权限；实际验收以相应发行包的验证记录为准。
