# 项目交接说明

## 1. 项目定位

当前仓库是 `LLM-Gateway（MaaSTaaTu）` 的腾讯云资源调度器原型。它负责
Lighthouse 和 TAT 的资源操作；LLM-Gateway 负责用户、会话、计费以及把用户的
HTTP/WebSocket 请求代理到对应的 Harness 工作区。

本仓库不是 `deepseek-harness` 的部署源码。腾讯云轻量应用服务器使用的是腾讯云
镜像，现有本地 clone 只用于确认 DSH 的行为和端口。

## 2. 当前目标架构

```text
用户浏览器
    |
    v
LLM-Gateway（MaaSTaaTu）
    |  调度器 API；后端代理请求时加 X-MaaSTaaTu-Proxy-Key
    v
云资源调度器（本项目）
    |  Lighthouse / TAT
    v
Lighthouse 实例
    |
    +-- Nginx :443（HTTPS + 网关专用密钥）
    |       |
    |       +--> 127.0.0.1:3080 DSH Web
    |
    +-- DSH 不直接监听公网
```

用户不应直接拿到实例 IP。实例公网入口只服务于 LLM-Gateway 后端。

## 3. 已验证的真实事实

实验实例：`lhins-qojobi8w`，区域：`ap-beijing`，公网 IP：`82.156.197.120`。

已通过实测确认：

- Lighthouse 实例可以处于 `RUNNING`。
- TAT Agent 在线，`RunCommand` 从 `RUNNING` 到 `SUCCESS`，可执行只读 Shell。
- 镜像中 DSH 已在运行，实际进程为
  `node /home/ubuntu/.local/share/pnpm/dsh --profile web`。
- DSH 监听 `127.0.0.1:3080`，本机访问返回 HTTP 200。
- TAT 的默认 PATH 不包含 `/home/ubuntu/.local/share/pnpm`；直接执行 `dsh`
  可能显示 `command not found`，但已启动的进程不受影响。
- Nginx 安装后，在实例内部访问 `http://127.0.0.1/` 能代理到 DSH 并返回 200。
- Lighthouse 防火墙开放 TCP/80 后，本地 `curl` 可以收到实例公网 HTTP 响应。
- `/api/` 返回 404 只说明该路径不存在，不能作为完整 API 验证。

## 4. 云端当前状态与代码状态

这两件事必须分开理解：

### 已经发生在实验实例上的变更

- 安装了 Nginx 和 curl。
- Nginx 曾配置为 HTTP `80 -> 127.0.0.1:3080`。
- 最近一次已知的 Lighthouse 防火墙规则包含 TCP/22、ICMP 和 TCP/80；代码更新后的 443 切换尚未执行。

### 已写入仓库但尚未在云端执行的变更

- `scripts/configure_nginx.sh` 已改为 HTTPS 443 和请求密钥校验。
- `firewall_port.py` 已支持删除旧端口并添加新端口。
- `tat_exec.py` 已支持 TAT 隐藏参数，避免代理密钥出现在普通任务输出中。

因此，接手者不要假设实验实例已经切换到 HTTPS；需要按第 7 节执行。

## 4.1 实例与蓝图的生命周期规则

实验实例是临时资产。实例被销毁、退还或重建后，实例内通过 TAT 或 SSH 做的
所有改动都会消失；只有已经成功创建并保留的 Lighthouse 蓝图才会留下。蓝图
创建本身也是异步云操作，收到 `BlueprintId` 不等于蓝图已经可以用于创建实例，
必须继续查询蓝图状态直到 `NORMAL`，并记录该 ID。

制作蓝图的强制流程：

1. 创建一台临时 Lighthouse 实例，并等待 Lighthouse `RUNNING`、TAT 在线和 DSH 就绪。
2. 用 `tat_exec.py` 执行通用安装/配置脚本，在临时实例上验证 Nginx、HTTPS、DSH API 和 WebSocket。
3. 不能直接从已注入真实代理密钥的实例制作共享蓝图。先执行清理脚本，删除 Nginx 中的真实密钥、证书私钥、备份目录和其他运行时凭据；保留的软件包可以进入蓝图，运行时配置必须在新实例创建后重新注入。
4. 调用 Lighthouse `CreateBlueprint`（当前由 `createimage.py` 实验脚本完成），等待蓝图状态为 `NORMAL`。
5. 用该蓝图创建一台全新的测试实例，重新执行密钥注入和实例配置，验证冷启动、HTTPS、认证、API 和 WebSocket。
6. 新实例验证通过后，才把蓝图 ID 写入创建配置；临时实例可以退还。若第 4 或第 5 步失败，不能把临时实例当作已持久化成果。

当前没有自动化的“清理秘密”“轮询蓝图状态”“从蓝图冷启动验证”脚本，接手实现
调度器时必须补上。`createimage.py` 中 `ForcePowerOff=False` 代表开机制作，可能
导致部分数据未备份；正式制作应评估停机制作或在维护窗口执行。

## 5. 文件和脚本说明

### 通用远程执行

`tat_exec.py` 是所有实例内操作的传输层。它负责读取本地 `.sh` 文件，Base64
编码后调用 TAT `RunCommand`，轮询 `DescribeInvocationTasks`，解码
`TaskResult.Output`，并用退出码表示成功或失败。

通用用法：

```bash
python tat_exec.py \
  --instance-id lhins-qojobi8w \
  --script scripts/configure_nginx.sh \
  --command-name configure-dsh-nginx \
  --parameter-env proxy_key=MAASTAAT_PROXY_KEY
```

只打印脚本、不发送云请求：

```bash
python tat_exec.py --instance-id lhins-qojobi8w \
  --script scripts/configure_nginx.sh --dry-run
```

### Nginx 配置

`scripts/configure_nginx.sh` 在实例内执行以下动作：安装 Nginx/OpenSSL，生成临时
自签名证书，配置 `443` 反代到 `127.0.0.1:3080`，检查
`X-MaaSTaaTu-Proxy-Key`，验证带密钥和不带密钥的本机 HTTPS 请求，并启用 Nginx
开机启动。

`configure_nginx_tat.py` 是针对实验实例 `lhins-qojobi8w` 的兼容包装器；正式
调度器不应依赖这个固定 ID。

### Lighthouse 防火墙

`firewall_port.py` 的修改接口提交的是完整规则列表，不是单独追加，因此脚本先
查询并保留旧规则，再添加目标规则。查询接口返回的空字符串字段会被过滤，避免
`Ipv6CidrBlock: ""` 造成 API 错误。

收紧到 443：

```bash
python firewall_port.py --port 443 --remove-port 80 --execute
```

### 资源实验脚本

- `createInstances.py`：使用固定套餐、蓝图和测试 ClientToken 创建 Lighthouse。
- `describeinstances.py`：查询实例；空请求会查询全部实例。
- `startinstances.py`：启动固定实例。
- `createimage.py`：调用 Lighthouse `CreateBlueprint`，从固定实例制作蓝图。
- `requestbundle.py`、`DescribeBundles.py`：查询套餐和折扣。
- `requestmirror.py`：查询蓝图。

这些脚本用于探索 SDK，不是最终服务层；它们仍有固定参数、输出文件和重复的
客户端初始化，后续应迁移到统一模块。

## 6. 凭据和安全约定

腾讯云控制面凭据：

```text
TENCENTCLOUD_SECRET_ID
TENCENTCLOUD_SECRET_KEY
```

只用于本地调度器调用 Lighthouse/TAT，不能作为网页访问密码。

网站到实例的代理密钥：

```text
MAASTAAT_PROXY_KEY
```

只用于 Nginx 校验 `X-MaaSTaaTu-Proxy-Key`。当前原型通过 TAT 隐藏参数传递，不应
写入 `docs/`、Shell 文件、镜像或 Git。生产环境应由 Secret Manager 注入。

当前脚本生成的是自签名证书。它适合验证加密和认证链路，不适合直接作为生产证书。
LLM-Gateway 必须使用内部 CA/域名证书，或者明确固定信任该实例证书；不能在正式
环境里无条件关闭 TLS 校验。

## 7. 接手后的建议执行顺序

1. 确认 `TENCENTCLOUD_SECRET_ID` 和 `TENCENTCLOUD_SECRET_KEY` 已通过安全方式
   注入 `tencentdsh` 环境。
2. 生成并保存代理密钥，不要写入仓库：

   ```bash
   export MAASTAAT_PROXY_KEY="$(openssl rand -hex 32)"
   ```

3. 在实验实例部署新 Nginx 配置：

   ```bash
   python configure_nginx_tat.py --execute
   ```

4. 配置成功后切换云防火墙：

   ```bash
   python firewall_port.py --port 443 --remove-port 80 --execute
   ```

5. 测试认证行为：

   ```bash
   curl -k -i -H "X-MaaSTaaTu-Proxy-Key: $MAASTAAT_PROXY_KEY" \
     https://82.156.197.120/
   curl -k -i https://82.156.197.120/
   ```

   第一条应到达 DSH Web；第二条应返回 `401 Unauthorized`。`-k` 是因为当前
   是自签名证书。

6. 再验证 DSH 的真实 API 路径、流式响应和 WebSocket，并在 LLM-Gateway 中实现
   后端代理。浏览器只访问 LLM-Gateway，不访问实例地址。
7. 完成 TLS 信任方案、镜像制作和新实例冷启动测试后，才创建正式 Lighthouse
   蓝图。不要把当前实例中的代理密钥和私钥直接固化进共享蓝图。
8. 最后实现调度器 REST API、状态持久化、幂等、超时重试、回收和对账。

## 8. 尚未实施的设计工作

- 创建接口的异步任务契约和状态机（`CREATING`、`BOOTSTRAPPING`、`READY`、
  `FAILED` 等）。
- 实例/工作区/租户/幂等键/任务的持久化模型。
- 调度器对 LLM-Gateway 的认证和资源授权。
- Lighthouse Start/Stop/Delete 的完整契约和计费语义。
- 创建实例后自动配置 Nginx、注入密钥、检测 TAT 和 DSH 就绪的编排流程。
- MaaSTaaTu 的 HTTP/WebSocket 反向代理实现。
- 固定出口、私网或其他网络访问控制方案。
- 正式证书、证书轮换、密钥轮换和审计日志。
- 失败时的实例回收、云端状态对账和孤儿资源清理。

## 9. 已知问题

- 当前实验脚本中的区域、实例 ID、套餐、蓝图和部分 ClientToken 仍是固定值。
- `createInstances.py` 中的测试 ClientToken 不能直接用于正式幂等实现。
- 旧探索脚本重复初始化 SDK 客户端，尚未抽成 Lighthouse/TAT 服务模块。
- 当前没有配置文件规范、测试套件或正式进程管理配置。
- 自签名证书的 SAN 只覆盖临时测试地址，不能直接满足严格的公网 IP/域名校验。
- Nginx 的共享密钥方案是第一版门禁；后续应评估每实例密钥、短期 Token、私网
  和来源白名单。
