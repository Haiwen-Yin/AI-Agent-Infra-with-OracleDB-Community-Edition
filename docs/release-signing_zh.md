# 发布压缩包签名 v4.4.15

升级服务使用运维人员配置的 `CX_RELEASE_SIGNING_PUBLIC_KEY` 验证 Ed25519
签名。该值是 32 字节公钥的 URL-safe Base64 编码。客户端提交的 `VERIFIED`
标签不能建立信任；请上传实际压缩包，仅提交元数据的暂存接口会拒绝请求。

在生成包目录中，为完成构建的压缩包签名：

```bash
python scripts/tools/sign_release_archive.py \
  --input /path/to/unsigned.zip --output /path/to/signed.zip \
  --private-key /secure/operator-ed25519.pem --key-id release-key
```

命令使用运维人员持有的未加密 Ed25519 PEM 私钥，请将文件权限限制为仅所有者可读。
命令创建新的压缩包，不覆盖已有输出，也不会将私钥放入包中。升级服务的可信公钥须由
运维人员独立配置，不能从上传包中直接信任一把新公钥。

`release-signature.json` 使用 `chuanxu-release-signature/v1` 格式，算法为
`ED25519`，签名对象为 `package-files.sha256`。其中摘要为文件清单原始字节的
SHA-256。签名输入由 ASCII 文本 `chuanxu-release-manifest/v1`、一个换行字符和
64 字符摘要组成；签名值使用 URL-safe Base64 编码。

文件清单覆盖全部有效载荷，包括 `build-manifest.json`，但不包含文件清单自身和签名
封装，避免摘要循环依赖。整个 ZIP 的摘要仍作为数据库中的压缩包身份。重复路径、包根目录
外的文件、内容篡改和不可信签名都会被拒绝。升级预检、启动滚动升级和 Skill 分发前，服务
会重新校验暂存包字节和当前信任公钥；Skill 版本必须与已验证包的版本一致。

缺少可信公钥或有效签名时，上传结果保持不可信，不能启动可信升级。签名通过本身不代表
版本已经可发布，也不能替代运行时和 Skill 交付全流程验收。

## Agent 下载与确认

已被指定接收该更新的活动 Agent，使用绑定实例的 Bearer 和 `skills.read` 范围轮询
`GET /api/agent-gateway/upgrades/skill-pending`。通过
`GET /api/agent-gateway/upgrades/{upgrade_id}/skill-archive?skill_version=VERSION`
下载精确压缩包。服务检查接收者分配关系及当前签名信任，返回禁止缓存的 ZIP 字节，不解压或执行包内容。

使用本地独立配置的可信公钥验证下载结果：

```bash
python scripts/tools/verify_release_archive.py \
  --input /path/to/downloaded.zip --public-key-file /secure/release-public-key.txt \
  --expected-digest EXPECTED_ZIP_SHA256
```

公钥文件内容为可信 32 字节 Ed25519 公钥的 URL-safe Base64 编码，不应从压缩包中取得
这份信任配置。验证命令检查整个 ZIP 摘要、全部清单条目、签名和 Skill 入口，不安装或执行
文件。失败时使用非零退出码，并输出经过脱敏的错误码。

验证成功后，向 `POST /api/agent-gateway/upgrades/skill-ack` 提交 `upgrade_id`、
`skill_version`、`verified: true`、已验证的 `received_digest` 以及 `safe_point`。
验证标志默认值为 false；旧客户端需要显式补充接收摘要。服务再次验证当前签名信任，
并在同一事务提交确认状态和审计。尚未到达安全切换点时，激活状态保持 OLD_VERSION，
更新继续出现在待处理列表。过期的失败确认不能撤销已激活的状态。安全切换点由经过认证
的 Agent 声明，这不等于独立证明外部进程已切换其安装的 Skill；实际运行切换仍需单独验证。

[English guide](release-signing.md)
