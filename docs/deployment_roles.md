# Deployment Roles

当前实现不是三套独立代码，而是 **同一个 Python 包，按命令承担不同角色**。

这是有意为之：编译机和执行机都安装同一份 `agent_remote`，这样 manifest、状态机、校验逻辑和结果格式保持一致。真正的角色差异体现在运行的命令和配置文件上。

## 三类角色

```text
编译机 Build Host
  安装 agent_remote
  运行 submit / status / logs / fetch
  负责上传 artifact、提交 job、读取结果

Relay
  当前已实现：文件系统 relay
  形态可以是共享目录、SMB/CIFS 挂载、SFTP/sshfs 挂载、Windows 目录
  当前没有常驻 relay 进程

执行机 Execution Host
  安装 agent_remote
  运行 worker
  负责拉取 job、校验 artifact、解包、执行命令、上传结果
```

## 是否需要配置 IP

分情况。

### 当前主模式：文件系统 relay

`agent_remote` 配置里不直接写 relay IP，而是写 `relay_root` 路径。

IP、账号、密码、端口这些信息在操作系统挂载层处理。例如：

```bash
sudo mount -t cifs //192.168.1.20/agent-remote /mnt/agent-remote
```

然后在 `agent_remote` 里只配置：

```json
{
  "targets": {
    "exec-a": {
      "relay_root": "/mnt/agent-remote"
    }
  }
}
```

也就是说：不是不需要 IP，而是当前文件系统 relay 模式把 IP 放在 SMB/SFTP/sshfs/企业网盘挂载配置里，不放在应用配置里。

### SSH direct 辅助模式

这里需要配置执行机地址：

```json
{
  "targets": {
    "exec-a": {
      "ssh_host": "user@192.168.1.30",
      "ssh_port": 22
    }
  }
}
```

### 尚未实现：HTTP relay service

如果不想做共享目录或挂载，而是希望 Windows PC 上跑一个 relay 服务，那么就需要类似：

```json
{
  "relay": {
    "type": "http",
    "url": "http://192.168.1.20:8080"
  }
}
```

这一块目前还没有实现。它应该是下一阶段的重点。

## 分角色配置

### 编译机配置

示例：`examples/build-host.relay.config.json`

编译机需要：

- `relay_root`
- profile 的 `cmd`
- profile 的 `collect`
- profile 的 `env`

编译机运行：

```bash
python -m agent_remote.cli --config examples/build-host.relay.config.json submit \
  --profile op-test \
  --artifact ./dist/op_package.tar.gz \
  --json
```

查询：

```bash
python -m agent_remote.cli --config examples/build-host.relay.config.json status \
  <job_id> \
  --target exec-a \
  --json
```

### 执行机配置

示例：`examples/execution-host.relay.config.json`

执行机需要：

- 同一个 `relay_root`
- `work_root`
- `allowed_commands`
- `allowed_profiles`

执行机运行：

```bash
python -m agent_remote.cli --config examples/execution-host.relay.config.json worker \
  --target exec-a
```

## 当前缺口

当前实现已经能跑通文件系统 relay，但还缺：

- Windows 上常驻 HTTP relay server。
- `relay_url` 形式的 IP/端口配置。
- 编译机和执行机通过 HTTP API 上传、拉取、claim、finish job。

所以如果你的 Windows PC 只是“网络中转”但不能提供共享目录或挂载目录，那么现在这版还不够，需要继续实现 HTTP relay backend。
