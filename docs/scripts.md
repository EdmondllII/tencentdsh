# 脚本使用说明

所有命令先执行：

```bash
conda activate tencentdsh
export TENCENTCLOUD_SECRET_ID='...'
export TENCENTCLOUD_SECRET_KEY='...'
```

不要把真实凭据写入任何 `.py`、`.sh`、`.json` 或 Markdown 文件。

## TAT 远程脚本

通用执行器：

```bash
python tat_exec.py --instance-id <lhins-id> --script scripts/<script>.sh
```

预览而不提交：

```bash
python tat_exec.py --instance-id <lhins-id> \
  --script scripts/<script>.sh --dry-run
```

需要传秘密时使用 TAT 隐藏参数：

```bash
export MAASTAAT_PROXY_KEY="$(openssl rand -hex 32)"
python tat_exec.py --instance-id <lhins-id> \
  --script scripts/configure_nginx.sh \
  --parameter-env proxy_key=MAASTAAT_PROXY_KEY
```

`scripts/configure_nginx.sh` 的当前行为：

1. 备份已有 `/etc/nginx`；
2. 安装 Nginx、curl、OpenSSL；
3. 生成临时自签名证书；
4. 配置 `443 -> 127.0.0.1:3080`；
5. 要求 `X-MaaSTaaTu-Proxy-Key`；
6. 检查 Nginx 语法、启动状态和本机 HTTPS 代理。

实验实例的兼容入口：

```bash
python configure_nginx_tat.py              # 只预览脚本
python configure_nginx_tat.py --execute    # 真正执行
```

## Lighthouse 防火墙

只读查看：

```bash
python firewall_port.py
```

开放 443 并删除 80：

```bash
python firewall_port.py --port 443 --remove-port 80 --execute
```

修改时脚本会先获取完整规则列表并保留原有规则。测试阶段使用
`0.0.0.0/0`，正式环境应改为网关固定出口或私网来源。

## 蓝图制作注意事项

实例内的 Shell/TAT 修改只存在于当前实例。实例退还后这些修改会消失，不能把
“TAT 执行成功”当作持久化。`createimage.py` 发起 Lighthouse `CreateBlueprint`
后，必须查询蓝图状态直到 `NORMAL`，再用蓝图创建新实例进行冷启动验证。

当前 Nginx 配置脚本会把运行时代理密钥写入实例配置，因此不能在执行完
`configure_nginx.sh` 后直接制作共享蓝图。应先清理真实密钥、证书私钥和用户数据，
并在每台新实例创建后重新注入。清理和蓝图状态轮询目前尚未自动化。

## DSH/TAT 探测

```bash
python probe_harness_tat.py --execute
```

探测是只读的，检查实例状态、TAT、DSH 进程、3080 监听和本机 HTTP。

## 资源查询和创建实验

`describeinstances.py`、`requestbundle.py`、`DescribeBundles.py`、
`requestmirror.py` 用于查询。`createInstances.py`、`startinstances.py` 和
`createimage.py` 会改变云端状态，执行前必须确认参数和目标实例；它们不是正式
调度器接口。
