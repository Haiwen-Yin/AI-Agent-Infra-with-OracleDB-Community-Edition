# Oracle AI 数据库记忆系统 v2.2.1

**版本**: v2.2.1 | **日期**: 2026-05-23 | **作者**: 尹海文 | **许可**: Apache License 2.0

> v2.2.1 是可视化架构升级版本，与 v2.2.0 数据库完全兼容，无需迁移。

---

## 一、v2.2.1 更新内容 — 可视化架构升级

v2.2.1 将单文件内联可视化（`viz_server_local_js.py`，963行）替换为模板化架构（`scripts/visualization/server.py` + 7个HTML模板 + 静态资源），带来现代化暗色主题UI。

### 架构对比

| 项目 | v2.2.0 | v2.2.1 |
|------|--------|--------|
| 服务端 | 单文件 `viz_server_local_js.py` (963行) | 模板化 `server.py` (519行) + 7模板 + CSS + JS |
| 导航 | 顶部按钮栏 | 左侧固定侧边栏（220px），6个页面链接 |
| 页面布局 | 简单表格 | Bootstrap Tabs、Accordion折叠、可展开详情行 |
| 双语切换 | 页面跳转后重置 | `localStorage` 持久化，跳转保持 |
| 自动登出 | 无倒计时 | 5分钟倒计时，60秒变色警告，30秒标题闪烁 |
| 图探索 | 无独立页面 | 独立Graph Explorer页面，统计卡片+搜索+详情面板 |

### 新增功能

| 功能 | 说明 |
|------|------|
| 左侧固定侧边栏 | 6个导航项（知识/记忆/智能体/任务/工作区/图探索）+ 语言切换 + 自动登出倒计时 |
| 知识/记忆双视图 | 表格列表 + 图可视化切换，按 domain/category 颜色分组 |
| 智能体 Bootstrap Tabs | 代理注册表 / 活跃会话 / 协作请求 三个Tab面板 |
| 任务 Accordion 折叠 | 计划展开/折叠，步骤详情，工具输入/输出，状态/优先级过滤 |
| 工作区可展开详情 | 点击行展开：上下文时间线 + 关联任务表 |
| Graph Explorer | 顶点/边/平均度统计卡片，搜索+类型过滤，节点上下文API，详情面板 |
| 双语持久化 | `data-zh`/`data-en` 属性切换，`localStorage` 保存语言偏好 |
| 5分钟自动登出 | 侧边栏倒计时显示，60秒变色，30秒标题闪烁警告 |

### 文件结构

```
scripts/visualization/
  server.py                 # HTTP服务（BaseHTTPRequestHandler, oracledb, session认证）
  templates/
    login.html              # 卡片式登录页，渐变背景
    knowledge.html          # 知识页：列表/图双视图 + 详情面板
    memory.html             # 记忆页：列表/图双视图 + 类别过滤
    agents.html             # 智能体页：Bootstrap Tabs
    tasks.html              # 任务页：Accordion折叠面板
    workspaces.html         # 工作区页：可展开详情行
    graph.html              # 图探索页：统计+搜索+可视化
  static/
    style.css               # 暗色主题CSS变量 + 侧边栏样式
    vis-network.min.js      # Vis.js 网络图库
```

### 兼容性

| 方面 | v2.2.0 → v2.2.1 |
|------|-----------------|
| 数据库Schema | **无变化** — 相同22个表、4个JRD视图 |
| PL/SQL包 | **无变化** — 相同5个包 |
| Python API层 | **无变化** — 相同10个模块、80+函数 |
| 调度器作业 | **无变化** — 相同9个作业 |
| 测试套件 | **无变化** — 61/61测试通过 |
| 可视化 | **替换** — 模板化架构 |

---

## 二、v2.2.0 核心变更 — 工作空间与上下文恢复

> 以下为 v2.2.0 引入的功能，v2.2.1 完全继承。

### 工作空间管理

- **WORKSPACES表** — 工作空间生命周期（ACTIVE → PAUSED → ARCHIVED），隔离模式（SHARED/ISOLATED）
- **WORKSPACE_CONTEXT表** — 上下文版本链（CHECKPOINT/HANDOFF/SUMMARY/ERROR_STATE/AUTO_SAVE）
- **WORKSPACE_TASKS表** — 任务-工作空间关联
- **workspace_api.py** — 11个Python函数：CRUD、上下文链、交接、恢复、任务关联

### 智能体交接

- **PREDECESSOR_SESSION_ID** — 会话交接链
- **OWNER_USER_ID / WORKSPACE_ID** — AGENT_SESSION新增列
- **checkpoint_session()** — 保存检查点到工作空间
- **get_session_chain()** — 遍历交接链

### JRD可写视图

- **WORKSPACE_DV** — 可写（INSERT/UPDATE/DELETE）
- **CONTEXT_DV** — 只读
- **MEMORY_DV / KNOWLEDGE_DV** — v2.2.0起可写

---

## 三、部署

### 从 v2.2.0 升级

无需数据库迁移，只需替换可视化文件：

```bash
./start_web_server.sh stop
rm viz_server_local_js.py vis-network.min.js
# 复制新的 scripts/visualization/ 目录
./start_web_server.sh start
```

### 全新部署

```bash
# 4阶段SQL部署
sql openclaw/hermes@//host:1521/service @scripts/deploy/1_schema.sql
sql openclaw/hermes@//host:1521/service @scripts/deploy/2_api.sql
sql openclaw/hermes@//host:1521/service @scripts/deploy/3_jobs.sql
sql openclaw/hermes@//host:1521/service @scripts/deploy/4_harness_templates.sql

# 启动可视化服务器
./start_web_server.sh start
```

---

## 四、版本历史

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| **v2.2.1** | 2026-05-23 | 模板化可视化、侧边栏导航、双语持久化、Graph Explorer、工作区详情视图 |
| **v2.2.0** | 2026-05-20 | 工作空间管理、上下文链、智能体交接、JRD可写视图、工作空间API |
| **v2.1.0** | 2026-05-15 | 表分区、复合主键、Property Graph API、Harness模板、JRD视图 |
| **v1.0.0** | 2026-05-01 | 初始版本 |
