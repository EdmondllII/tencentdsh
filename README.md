# Tencent DSH Cloud Resource Scheduler

这个项目是腾讯云 Lighthouse / TAT 的实验和调度器原型，目标是为
`LLM-Gateway（MaaSTaaTu）` 按需创建、配置、查询和回收 DeepSeek Harness
工作区。`deepseek-harness` 只是参考项目；腾讯云实例中的 DSH 由腾讯云镜像提供。

当前项目还不是可部署的 REST 调度器。现阶段完成的是云 API 调用验证、TAT
远程执行器和 Nginx 反向代理原型。接手开发时先阅读
[交接文档](docs/handoff.md)，再阅读 [设计与实施计划](docs/plan.md)。

## 当前状态

已验证：

- Lighthouse 实例 `lhins-qojobi8w` 可以创建和查询。
- TAT Agent 可在实例内执行 Shell，并返回任务结果。
- 腾讯云 DSH 镜像已自动启动 DSH，监听 `127.0.0.1:3080`。
- Nginx 反向代理到 DSH 的内部链路可用。
- 通过 Lighthouse 防火墙开放 TCP/80 后，本地可访问实例公网地址。

代码已准备但尚未部署到云端：

- Nginx HTTPS 443 配置和网关专用请求密钥校验。
- 关闭 TCP/80、开放 TCP/443 的防火墙变更。

尚未实现：REST 调度器、持久化、异步任务、MaaSTaaTu 代理接入、正式证书和
完整的 WebSocket/API 端到端测试。

注意：临时实例内的改动不会自动保留。只有状态为 `NORMAL` 的 Lighthouse 蓝图
才是持久化成果；制作蓝图前必须清理运行时密钥、证书私钥和用户数据，创建新实例
后再注入实例专用配置。完整流程见 [交接文档](docs/handoff.md) 的实例生命周期章节。

## 快速操作

使用 conda 环境：

```bash
conda activate tencentdsh
export TENCENTCLOUD_SECRET_ID='...'
export TENCENTCLOUD_SECRET_KEY='...'
```

只读探测实例和 TAT：

```bash
python probe_harness_tat.py --execute
```

在实例内配置 Nginx HTTPS（执行前设置网站与实例之间的专用密钥）：

```bash
export MAASTAAT_PROXY_KEY="$(openssl rand -hex 32)"
python configure_nginx_tat.py --execute
```

切换 Lighthouse 防火墙入口：

```bash
python firewall_port.py --port 443 --remove-port 80 --execute
```

真实密钥不得写入仓库、文档或命令行参数。`MAASTAAT_PROXY_KEY` 应由部署环境的
Secret 管理系统保存。

## 文件导航

| 文件 | 用途 |
| --- | --- |
| `docs/plan.md` | 设计目标、边界、接口草案和待解决事项 |
| `docs/handoff.md` | 当前进度、决策、已验证事实和后续执行手册 |
| `tat_exec.py` | 通用 TAT Shell 执行器，负责编码、轮询和输出 |
| `scripts/configure_nginx.sh` | 实例内安装和配置 Nginx HTTPS 反向代理 |
| `configure_nginx_tat.py` | 固定实验实例的兼容入口 |
| `firewall_port.py` | 查询/修改 Lighthouse 防火墙规则 |
| `probe_harness_tat.py` | 只读检查 DSH、TAT、3080 监听和本机 HTTP |
| `createInstances.py` | Lighthouse 创建实例实验脚本 |
| `describeinstances.py` | Lighthouse 查询实例实验脚本 |
| `startinstances.py` | Lighthouse 启动实例实验脚本 |
| `createimage.py` | Lighthouse `CreateBlueprint` 实验脚本 |
| `requestbundle.py` / `DescribeBundles.py` | 套餐和价格查询实验脚本 |
| `requestmirror.py` | 蓝图查询实验脚本 |
| `*.json` / `*.jsonc` | 实测返回和请求模板，不是运行时数据库 |

所有 Python 脚本都从环境变量读取腾讯云凭据；不要把凭据填回源文件中的旧示例。
