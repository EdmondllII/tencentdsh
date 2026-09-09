# 项目设计文档：云资源调度器 (Cloud Resource Scheduler)

## 1. 项目概述

### 1.1 项目背景
LLM-Gateway（MaaSTaaTu）需要为用户提供按需的 DeepSeek Harness 工作区能力。为避免将云 API 管理逻辑耦合进主业务，决定独立出一个专门负责腾讯云资源调度的服务。

### 1.2 核心目标
*   将"云资源管理"与"业务应用"解耦。
*   提供一套标准化的 RESTful API，供 LLM-Gateway（MaaSTaaTu）调用，以管理 Harness 实例的完整生命周期。
*   屏蔽底层腾讯云 API 的复杂性与差异。

---

## 2. 系统架构与分工

| **组件** | **角色** | **核心职责** | **对外暴露** |
| :--- | :--- | :--- | :--- |
| **云资源调度器** (新项目) | **资源管家** | 封装腾讯云 Lighthouse & TAT SDK，负责所有与云 API 的交互。管理实例的创建、查询、启停、销毁。管理实例的内部状态。 | RESTful API |
| **LLM-Gateway（MaaSTaaTu）** (现有项目) | **业务应用** | 处理用户请求。根据用户会话调用调度器 API。充当用户与 Harness 服务之间的 HTTP/WebSocket 代理。提供用户界面。 | Web UI / 用户浏览器 |

---

## 3. 详细权责边界

### 3.1 云资源调度器 (Resource Scheduler) 的权责

**负责**：
*   **资源生命周期管理**：提供 `Create`、`Start`、`Stop`、`Delete`、`Describe`（查询）等标准接口。
*   **远程命令执行**：通过 TAT 在实例内部执行脚本，例如启动 Harness Web 服务。
*   **网络配置**：负责管理防火墙规则（正式入口为 443），并通过 TAT 配置实例内的 Nginx 反向代理。
*   **状态维护**：维护实例的当前状态（如 `CREATING`、`RUNNING`、`STOPPED`、`ERROR`），并提供查询接口。
*   **错误封装**：将腾讯云 SDK 抛出的原始错误转换为调度器内部的标准错误码，返回给调用方。
*   **资源回收**：提供主动销毁实例的接口。

**不负责**：
*   用户认证与鉴权。
*   用户会话管理。
*   用户数据存储。
*   业务逻辑（如用户何时该创建实例）。
*   与 Harness 服务本身的业务交互（如调用 Harness 的 API 执行 AI 任务）。

### 3.2 LLM-Gateway（MaaSTaaTu，业务应用）的权责

**负责**：
*   **用户交互**：提供 UI 界面，让用户点击"初始化工作区"。
*   **会话管理**：管理用户会话，在用户登录/登出时决定何时调用调度器 API。
*   **调用调度器**：在需要时调用调度器的 API 来创建、启动或销毁实例。
*   **代理 Harness 流量**：充当用户浏览器与 Harness 服务之间的 HTTP/WebSocket 代理。浏览器只访问 LLM-Gateway，LLM-Gateway 后端再通过 HTTPS 443 和专用请求密钥访问实例 Nginx；实例 Nginx 转发到 `http://127.0.0.1:3080`。
*   **计费与配额**：管理用户的资源使用配额和计费展示。

**不负责**：
*   直接调用腾讯云 Lighthouse 或 TAT SDK。
*   管理云资源的底层状态（如判断实例是否真的启动成功）。

---

## 4. 交互流程与契约

### 4.1 交互流程 (用户视角)
1.  **用户**：访问 LLM-Gateway（MaaSTaaTu）页面，点击"创建我的 Harness 工作区"。
2.  **LLM-Gateway（MaaSTaaTu）**：调用调度器 `POST /api/v1/instances` 接口，请求创建一个 Harness 实例。
3.  **调度器**：
    *   调用腾讯云 `CreateInstances` API 创建轻量服务器。
    *   轮询 `DescribeInstances`，等待实例变为 `RUNNING` 并获取公网 IP。
    *   确认镜像中的 DSH 和 TAT Agent 就绪。
    *   通过 TAT 执行实例配置脚本，安装/启动 Nginx，配置 HTTPS 443 到 `127.0.0.1:3080` 的反向代理，并注入网关专用请求密钥。
    *   调用 `ModifyFirewallRules` API，放行 443，删除 80；3080 不开放公网。
    *   通过 HTTPS、请求密钥、DSH API 和 WebSocket 就绪探针后，更新内部状态为 `READY`。
    *   将工作区 ID 和代理端点信息返回给 LLM-Gateway，不向用户暴露实例管理凭据。
4.  **LLM-Gateway（MaaSTaaTu）**：保存工作区映射和代理密钥，将用户请求转发到实例 HTTPS 入口。
5.  **用户**：只在 LLM-Gateway 页面操作，不直接访问云服务器公网地址。
6.  **用户**：关闭页面或点击"释放"按钮。
7.  **LLM-Gateway（MaaSTaaTu）**：调用调度器 `DELETE /api/v1/instances/{instanceId}` 接口。
8.  **调度器**：调用腾讯云 `TerminateInstances` API 销毁实例，释放资源。

### 4.2 接口契约（调度器提供给 LLM-Gateway（MaaSTaaTu）的标准 API）

*   **创建实例**
    *   `POST /api/v1/instances`
    *   Request Body: `{"plan": "basic"}` (可选参数，便于未来扩展套餐)
    *   Response（最终建议）：`{"instance_id": "lhins-xxx", "endpoint": "https://...", "status": "PROVISIONING"}`

*   **查询实例状态**
    *   `GET /api/v1/instances/{instance_id}`
    *   Response：`{"instance_id": "lhins-xxx", "endpoint": "https://...", "status": "READY", "error": null}`

*   **销毁实例**
    *   `DELETE /api/v1/instances/{instance_id}`
    *   Response: `{"message": "instance terminated"}`

---

## 5. 关键约束与注意事项

*   **幂等性**：调度器的创建接口需要支持幂等性，防止 LLM-Gateway 因网络重试而创建多个实例。
*   **超时与重试**：由于云 API 调用耗时较长（创建实例可能需要几分钟），调度器应采用异步任务模式，或设置较长的 HTTP 超时时间。
*   **错误处理**：调度器应将云 API 的错误转换为业务语义明确的错误（如 `INSUFFICIENT_BALANCE`、`QUOTA_EXCEEDED`），返回给 MaaSTaaTu 友好展示。
*   **入口安全**：公网只开放 HTTPS 443；优先限制为 LLM-Gateway 固定出口或私网来源。Nginx 还必须校验 `X-MaaSTaaTu-Proxy-Key`，并在转发前删除该请求头。
*   **凭据隔离**：腾讯云 SecretId/SecretKey 只用于调用云 API；工作区代理密钥单独生成、注入和轮换，不能写入仓库或共享镜像。
*   **TLS**：自签名证书只用于实验。生产环境必须使用 LLM-Gateway 能验证的内部 CA/域名证书，禁止无条件关闭 TLS 校验。

## 6. 总结

通过引入"云资源调度器"，**LLM-Gateway（MaaSTaaTu）将获得一个清晰的、与云厂商无关的资源管理抽象层**。LLM-Gateway 不再需要关心 `CreateInstances` 的参数细节或 TAT 的 Base64 编码，只需调用简单的 REST 接口即可完成复杂的云资源操作。这种分层设计将显著提升系统的可维护性和可扩展性。

---

## 7. 待解决事项

### 7.1 已完成实测：腾讯云镜像与 TAT

对实例 `lhins-qojobi8w` 的只读探测结果：

*   Lighthouse 实例状态为 `RUNNING`。
*   TAT Agent 正常工作，可以提交并完成远程命令。
*   镜像中已有 DSH，实际进程为 `node /home/ubuntu/.local/share/pnpm/dsh --profile web`。
*   DSH 本机访问 `http://127.0.0.1:3080/` 返回 HTTP 200。
*   DSH 当前只监听 `127.0.0.1:3080`，没有直接监听公网地址。
*   TAT 执行环境的 `PATH` 中没有 `/home/ubuntu/.local/share/pnpm`，因此直接执行 `dsh` 会显示 `command not found`；这不影响已启动的 DSH 进程。

### 7.2 尚待设计或验证

1.   **公网访问入口**：Nginx HTTPS 反向代理和请求密钥代码已完成，尚需在实验实例部署并验证 WebSocket、长连接和真实 `/api` 路径；生产入口还需完成证书信任和来源限制。
2.   **异步创建契约**：确定创建接口返回 `202 Accepted` 加任务 ID，还是保持同步长请求；定义任务查询、超时和取消语义。
3.   **持久化与故障恢复**：设计实例、工作区、幂等键和异步任务的持久化模型，以及服务重启后的云端状态对账和孤儿资源回收。
4.   **调用方认证与资源授权**：调度器需要认证 MaaSTaaTu，并校验工作区与实例的归属，不能仅凭实例 ID 执行操作。
5.   **生命周期语义**：补充 Start、Stop、Delete 等接口契约，明确停机保留、销毁、数据保留和计费行为。
6.   **镜像启动契约**：确认镜像中 DSH、TAT Agent、运行用户、工作区目录和开机自启的稳定契约。
7.   **云厂商中立性边界**：明确当前只是向 MaaSTaaTu 隐藏腾讯云细节，并不意味着已经实现多云资源抽象。
8.   **蓝图持久化流程**：实例退还后实例内改动会消失；必须先清理运行时密钥和私钥，再创建并等待 Lighthouse 蓝图为 `NORMAL`，使用蓝图新建实例进行冷启动复验后才能作为正式模板。

### 7.3 当前公网入口安全方案

*   DSH 继续只监听实例内部的 `127.0.0.1:3080`。
*   Nginx 对外提供 HTTPS `443`，并将请求反向代理到 DSH。
*   LLM-Gateway 访问实例时必须携带专用请求头 `X-MaaSTaaTu-Proxy-Key`；Nginx 拒绝缺失或错误的密钥，并在转发给 DSH 前删除该请求头。
*   `TENCENTCLOUD_SECRET_ID` 和 `TENCENTCLOUD_SECRET_KEY` 只用于调度器调用腾讯云 API，不用于访问 DSH。
*   密钥通过环境变量 `MAASTAAT_PROXY_KEY` 提供给本地执行器，再以 TAT 隐藏参数传入实例；真实密钥不得写入仓库或 `docs/`。
*   当前配置脚本生成自签名证书用于网关到实例的加密连接。LLM-Gateway 必须显式信任该证书或其指纹；正式环境应改用可验证的内部 CA/域名证书。
*   Lighthouse 防火墙只开放 TCP `443`，关闭 TCP `80`。测试期间如曾开放 `80`，应使用 `firewall_port.py --port 443 --remove-port 80 --execute` 收紧规则。

### 7.4 当前交接状态

*   **实验验证完成**：Lighthouse、TAT、镜像内 DSH、`127.0.0.1:3080` 和 HTTP 80 反向代理均已实测。
*   **本地代码完成**：通用 TAT 执行器、Nginx HTTPS/密钥配置脚本、防火墙 443/80 切换脚本已写入仓库，并通过本地 Python/Shell 语法检查。
*   **云端新配置未执行**：实验实例最近一次已知状态仍是 HTTP/80 入口；不能假设已部署 HTTPS 443。需要设置 `MAASTAAT_PROXY_KEY` 后执行配置脚本，再切换防火墙。
*   **调度器本体未开始**：尚未实现 REST 服务、状态存储、异步编排、MaaSTaaTu 代理接入和自动回收。
*   **接手入口**：先阅读 `docs/handoff.md` 和 `docs/scripts.md`，按交接文档第 7 节继续。

### 7.5 实例退还与蓝图制作

临时实例上的安装、Nginx 配置、证书和密钥不会在实例退还后保留。持久化成果只有
成功创建且状态为 `NORMAL` 的 Lighthouse 蓝图。当前 `createimage.py` 可以发起
`CreateBlueprint`，但尚未轮询蓝图状态，也没有自动清理运行时秘密或用新实例复验。

蓝图不得包含：

*   `MAASTAAT_PROXY_KEY` 的真实值；
*   `/etc/nginx/tls/server.key` 和只属于某个实例的证书；
*   腾讯云 SecretId/SecretKey、SSH 私钥、TAT 临时输出和用户数据。

新实例的正确编排顺序是：创建实例 -> 等待 DSH/TAT -> 安装通用 Nginx -> 运行时注入
代理密钥和证书 -> 配置防火墙 443 -> 就绪探针 -> 对外提供服务。蓝图制作只保存
通用依赖和不含秘密的基础配置。
