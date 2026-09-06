# 川序：Oracle AI Database 26ai 社区版 v4.4.12 中文介绍

**版本**: v4.4.12
**日期**: 2026-09-05
**许可**: Apache License 2.0

[返回 README](../README.md) · [官方网站](https://db4agent.cn)

## 平台用途

川序（Chuanxu）是基于数据库的 AI Agent 管理平台，为企业内部及外部智能体保存身份、组织、知识、记忆、工作上下文、任务状态及治理记录。数据库负责持久状态和数据授权，模型负责推理与生成，Agent 运行进程负责执行。三者凭据和权限分别管理。

技术项目名为 AI Agent Infra with DB。本包只适配 Oracle AI Database 26ai。Community 与 Enterprise 从同一仓库生成，有效能力取决于发行版、平台开关和主体权限。

## 功能与边界

| 功能 | 用途 | 使用边界 |
|---|---|---|
| 组织与人员 | 组织层级、人员主组织、Agent 责任人和入口权限 | 组织成员关系不授予所有资源权限 |
| Agent Pool | 模型配置、运行准入、会话分配和健康检查 | 配置记录不等于已有健康执行进程 |
| 外部 Agent | 一次性注册授权、凭据激活、权限与吊销 | 不分发 schema owner 密码 |
| 知识 | 全公司、组织子树、组织层级、人员/Agent 私有范围 | 按当前数据库策略过滤，兄弟部门不自动互通 |
| 记忆 | 稳定族、不可变版本、整理候选和受控遗忘 | 模型输出不是事实或授权证明 |
| 工作区与分支 | 上下文保存、隔离变化、来源记录和合并 | 合并需要授权与冲突检查 |
| 任务与循环 | 步骤依赖、工具调用、迭代和停止条件 | 文字计划不能替代执行证据 |
| 图工程 | 定义、编译、运行、事件、检查点和属性图溯源 | 关系数据保存运行与恢复权威状态 |
| 安全域与频道 | 明确成员与范围，承载协作消息 | 消息不扩大数据权限 |
| 协作关卡 | 到达、复核、继续或返工 | 操作按权限和发行版开放 |
| 模型网关 | 可选转发、用量、配额和账单核对 | 直连与网关可并行，未观测直连不视为零消耗 |
| Embedding | 统一模型契约、维度、预处理和绑定 | 外部模型须做匹配验证，不只比名称 |
| 管理大屏 | 登录后只读运行态、模型趋势和覆盖率 | 不提供配置或审批操作 |
| 企业治理 | 审批、合规姿态、审计及企业身份集成 | Enterprise 专属模块不作为 Community 承诺 |

旧“协作”独立页面已移除。新协作通过安全域、频道、工作区、分支和关卡完成；历史协作组仅为内部兼容记录，不是新授权入口。

## 隔离、图工程与 DB4A2A

本地强隔离运行依赖独立 UID/GID、namespace、cgroup、seccomp 和受保护的 Host Manager。控制面能够启动不等于宿主机通过强隔离准入。阅读 [Linux 兼容性](linux-platform-compatibility.md) 和 [运行隔离](runtime-isolation.md)。其他容器、云或 MaaS/SaaS 目标需要适配器与实际环境验证。

DB4A2A 的委派携带上下文引用、版本、摘要和范围，接收 Agent 仍须独立认证授权。它用于共享数据平面的协作，不替代标准 A2A 互操作。具体实现与未完成验证见 [DB4A2A](db4a2a.md) 及发布证据；接口存在不能证明全部不变量均已实测。

Graph Runtime 核心和图检查按权限提供。Manifest Draft Import、SLO 只读及 Checkpoint Fork 为受控能力；Replay、Dynamic Graph Migration、Framework Adapter Execution、A2A 和 OTLP 当前为 DISABLED，不属于本版可启用的交付能力。不能由提示词或 Skill 自动开启。详见 [图工程](graph-engineering.md)。

## 数据库适配

向量、全文、Property Graph、关系数据和 PL/SQL；DBA 须准备 PDB、表空间与组件授权。网络加密策略须与 python-oracledb thin/thick 模式匹配。

业务凭据失效时不得回退到部署账户。应用层检查不能替代数据库内部的行级/对象级授权。参见 [最小权限](minimum-privileges.md)、[安全](security.md) 和 [架构](architecture.md)。不以手工统计的表、函数或索引数量承诺当前能力；实际对象由发行清单和 postflight 核验。

## 从空目标部署

先阅读 [部署说明](deployment.md)，由 DBA 完成包内 `scripts/deploy/0_oracle_database_prerequisites.sql` 对应的前置操作，准备独立空目标。数据库安装、PDB 创建、恢复与基础设施权限由数据库运维负责。

在解压后的发行包根目录执行：

```bash
bash scripts/install_offline.sh
bash scripts/config_wizard.sh
bash scripts/install_platform.sh initialize \
  --version 4.4.12 --database oracle \
  --edition community --config config.json
bash start_web_server.sh start
bash start_web_server.sh status
```

上例适用于 Community；Enterprise 包将 `--edition community` 改为 `--edition enterprise`。使用可访问的 Python 3.14 和匹配依赖。初始化按清单执行 SQL、核对迁移记录和 postflight；不要只运行少数历史 SQL。

配置向导设置数据库连接、Web 监听地址/端口、LLM 地址、模型 ID 和凭据，执行服务探测。Embedding 使用统一契约。初始 admin 密码由初始化流程输入，不存在通用默认密码；首次初始化不要求客户端备份文件。已有数据按 [迁移](migration.md) 与数据库恢复策略处理。

## Web 与外部接入

使用配置的地址访问管理应用和 Portal。管理页面使用 `/app/monitor` 等 `/app/*` 路由，菜单按发行版和权限显示。不要沿用旧 `/collab`、固定端口或固定登出倒计时。

外部可访问性由监听、反向代理及防火墙共同决定。外部 Agent 按 [SKILL.md](../SKILL.md) 注册；若配置外部数据库地址，注册分发使用对外地址，服务名与目标库一致。公网地址和凭据分别管理，不能包含部署账户密码。

## 运维与进一步阅读

初始化失败应保留脱敏错误、迁移位置和 postflight 结果，按数据库文档修复；不反复清空目标掩盖原因。运行问题先查服务状态、数据库连接、会话、权限和能力开关，再核对模型健康与 Embedding 契约。

数据库、页面、运行隔离分别验收，任何一种通过不能替代其他测试。参见 [恢复](recovery.md)、[模型用量](model-usage-and-wallboard.md)、[组织治理](organization-governance.md)、[API](api-reference.md)。

## 许可与作者

**社区版**：Apache License 2.0

可在 Apache License 2.0 条款下使用、修改和分发。

完整条件见 [LICENSE](../LICENSE)。Community 的 Apache 2.0 不禁止生产使用；Enterprise 商业使用按随包许可确认。企业支持和数据库厂商许可分别确认。

作者：尹海文（Haiwen Yin）。
