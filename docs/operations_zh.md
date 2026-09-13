# 川序 v4.4.14 运维与技术说明（中文）

本文是发行包中的中文技术入口，覆盖部署、迁移、恢复、安全、模型能力和发布判断。
英文文件保留完整参数、接口和 SQL 参考。

## 部署

准备匹配发行版的数据库、Python 3.14 和离线依赖。解压后依次运行
`scripts/install_offline.sh`、`scripts/config_wizard.sh`、
`scripts/install_platform.sh initialize`，再运行 `start_web_server.sh start`。
Oracle/YashanDB 执行对应的数据库前置脚本；PostgreSQL 准备独立数据库和扩展。
初始化时输入管理员密码，包内没有通用默认密码。部署后检查 `/health`、`/ready`、
迁移账本、能力矩阵和最小权限。

详细说明：[deployment.md](deployment.md)。

## 升级与迁移

v4.4.14 新安装基线终止于迁移 82。升级前完成数据库原生备份，使用包内入口执行
预检、确认和带校验的顺序迁移。Oracle/YashanDB 与 PostgreSQL 的迁移尾部不同，
不能跨数据库复制 SQL。预检失败时保留日志并修复原因，不清空目标库掩盖问题。

详细说明：[migration.md](migration.md)。

## 恢复与隔离

运行状态、租约、围栏令牌、任务、检查点和审计记录以数据库为准。进程重启只回收
本节点已经过期的租约；旧 Worker 不能提交过期围栏令牌。数据库不可用时停止新的
副作用，不使用内存状态绕过授权。数据库复制、备份、主备切换、RPO/RTO 由部署方负责。

详细说明：[recovery.md](recovery.md)、[runtime-isolation.md](runtime-isolation.md)、
[linux-platform-compatibility.md](linux-platform-compatibility.md)。

## 安全与权限

Human、平台 Agent、外部 Agent 和 Schema Owner 使用不同身份。凭据失效时不能回退到
部署账户；知识按公司公开、组织子树、组织级和 Human/Agent 私有范围过滤。安全域是
协作授权边界，频道只承载消息，不扩大数据权限。Enterprise 审批、审计和应急控制由
服务端与数据库共同执行。

详细说明：[security.md](security.md)、[minimum-privileges.md](minimum-privileges.md)。

## 模型、MCP 与 A2A

能力状态为 `OFF`、`READ_ONLY`、`PROPOSAL_ONLY` 或 `GOVERNED_EXECUTOR`。MCP/A2A 默认
关闭；模型生成的写入、策略变更、Agent 控制、外部联系和发布默认只能形成提案。
供应商证据记录模型身份、校验、工具调用、用量、延迟、超时、取消、重试和完成状态，
不保存隐藏推理内容或完整提示词。未被网关观测的直连流量不能报告为零消耗。

详细说明：[model-usage-and-wallboard.md](model-usage-and-wallboard.md)、[api-reference.md](api-reference.md)。

## 图、组织与 DB4A2A

Graph Runtime 的运行、租约、检查点和事件是数据库事实；图只是授权后的投影。DB4A2A
传递受版本、摘要和范围约束的上下文引用，接收 Agent 仍须独立认证授权，不代表标准
A2A 互操作。

详细说明：[graph-engineering.md](graph-engineering.md)、[organization-governance.md](organization-governance.md)、
[db4a2a.md](db4a2a.md)。

## 发布判断

当前版本的源码、发行包、数据库、UI、依赖、POC 和支持包证据统一记录在
`release_evidence/manifest.json`；只有清单为 `PASS` 才能标记为可发布。
