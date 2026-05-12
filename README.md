# agent-remote

`agent-remote` 是一套给 AI 辅助开发场景使用的远端执行框架。它解决的核心问题是：

- 代码和算子包在编译机上开发、编译。
- 二进制包需要到另一台 Linux 执行机上运行、调试或 benchmark。
- 编译机上的 AI agent 需要一个稳定的命令行入口，把产物发过去、触发执行、取回日志和结果。
- 当编译机和执行机网络不互通时，可以使用 Windows 个人 PC 作为中转。

当前版本的主模式是 **Relay + Worker Polling**：

```text
编译机 submit -> relay 队列 -> 执行机 worker 主动拉取 -> relay 结果回传 -> 编译机 fetch/logs/status
```

这个模式也是最推荐给 AI agent 使用的默认路径，因为执行机不需要开放入站端口，编译机和执行机不互通时也可以通过 Windows PC 中转。

先把一个容易误解的点说清楚：当前实现是 **同一份 Python 包，按命令区分角色**，不是三套代码仓库。

- 编译机安装这份包，运行 `submit/status/logs/fetch`。
- 执行机安装这份包，运行 `worker`。
- Relay 在当前版本里不是常驻进程，而是一个共享目录或挂载目录。

如果你的 Windows PC 只是一个共享目录、SMB/CIFS 目录、SFTP/sshfs 挂载点，那么当前版本可以工作，IP 配在挂载层。如果你希望 Windows PC 跑一个 HTTP relay 服务，通过 `http://<ip>:<port>` 访问，那是下一阶段要实现的 HTTP relay backend，当前还没有完成。

当前版本已经支持：

- 文件系统 relay 队列，适合共享目录、SFTP 挂载目录、Windows 中转目录。这是主模式。
- 执行机 worker 主动拉取任务。
- artifact SHA-256 校验。
- tar/zip 解包，普通文件复制。
- 命令执行、超时控制、stdout/stderr 捕获。
- 结果文件按 glob 收集。
- JSON 输出，方便 Claude Code 等 AI 工具解析。
- profile 配置，减少 agent 反复拼长命令。
- 命令白名单和 profile 白名单。
- relay 审计日志。
- SSH direct 辅助模式，适合编译机能直连执行机时快速跑一次。

## 适用场景

推荐拓扑：

```text
编译机 Linux
  开发代码 / 编译算子包 / AI agent
       |
       | remote-run submit
       v
Relay
  可以是共享目录、SFTP 挂载目录、Windows PC 目录
       ^
       | remote-run worker polling
       |
执行机 Linux
  解包 / 执行测试 / 采集日志 / 上传结果
```

辅助拓扑：

```text
编译机 Linux
  remote-run ssh-submit
       |
       | scp + ssh
       v
执行机 Linux
  临时远端 relay / worker once / 结果回传
```

除非你明确只想做一次直连调试，否则建议优先使用 relay 模式。

更详细的分角色部署说明见：[docs/deployment_roles.md](docs/deployment_roles.md)。

## 安装方式

开发态直接运行：

```bash
cd /path/to/agent_remote
PYTHONPATH=src python3 -m agent_remote.cli --help
```

安装成命令：

```bash
cd /path/to/agent_remote
python3 -m pip install -e .
remote-run --help
```

后面的示例统一使用 `python -m agent_remote.cli`，默认你已经执行过 `python3 -m pip install -e .`。如果没有安装，请在命令前加 `PYTHONPATH=src`。如果你已经安装了 console script，也可以把它替换成 `remote-run`。

## CLI 参数规则

`--config` 和 `--relay-root` 是全局参数，必须放在子命令前面：

```bash
python -m agent_remote.cli --config examples/remote-run.config.json submit ...
python -m agent_remote.cli --relay-root .agent-remote/relay status <job_id>
```

不要写成：

```bash
python -m agent_remote.cli submit --config examples/remote-run.config.json ...
```

## 主模式命令速查

日常使用优先记住这一组命令：

```bash
# 编译机：提交任务到 relay
python -m agent_remote.cli --config examples/remote-run.config.json submit \
  --profile op-test \
  --artifact ./dist/op_package.tar.gz \
  --json

# 执行机：长期运行 worker，从 relay 拉取任务
python -m agent_remote.cli --config examples/remote-run.config.json worker \
  --target exec-a

# 编译机：查询状态
python -m agent_remote.cli --config examples/remote-run.config.json status \
  <job_id> \
  --target exec-a \
  --json

# 编译机：查看日志
python -m agent_remote.cli --config examples/remote-run.config.json logs \
  <job_id> \
  --target exec-a \
  --tail 200

# 编译机：拉取结果
python -m agent_remote.cli --config examples/remote-run.config.json fetch \
  <job_id> \
  --target exec-a \
  --out ./results/<job_id>
```

`ssh-submit` 不在主模式速查里。它适合直连环境下偶尔快速跑一次，不建议作为 AI agent 的长期默认入口。

## 编译机、Relay、执行机分别做什么

| 角色 | 是否安装 agent_remote | 运行命令 | 主要配置 |
| --- | --- | --- | --- |
| 编译机 | 是 | `submit`、`status`、`logs`、`fetch` | `relay_root`、profiles |
| Relay 共享目录 | 否 | 不运行命令 | 由 SMB/SFTP/sshfs/共享盘提供路径 |
| 执行机 | 是 | `worker` | `relay_root`、`work_root`、白名单 |

示例配置：

- 编译机：[examples/build-host.relay.config.json](examples/build-host.relay.config.json)
- 执行机：[examples/execution-host.relay.config.json](examples/execution-host.relay.config.json)

当前主模式下，应用配置里不写 relay IP，而是写挂载后的路径：

```json
{
  "targets": {
    "exec-a": {
      "relay_root": "/mnt/agent-remote"
    }
  }
}
```

IP 在挂载层配置，例如：

```bash
sudo mount -t cifs //192.168.1.20/agent-remote /mnt/agent-remote
```

如果不想挂载共享目录，而是要配置 `relay_url = http://192.168.1.20:8080`，那说明需要 HTTP relay backend。这个 backend 还没实现，是下一阶段要补的核心能力。

## 主模式：Relay 目录结构

relay 是编译机和执行机共享的任务队列目录，也是本项目的核心运行模式：

```text
.agent-remote/relay/
  artifacts/
    <sha256>-op_package.tar.gz
  jobs/
    pending/
      <job_id>.json
    running/
    done/
    failed/
    timeout/
    canceled/
  results/
    <job_id>/
      stdout.log
      stderr.log
      meta.json
      tree.txt
      collected/
  audit/
    events.jsonl
```

各目录含义：

- `artifacts/`：按 SHA-256 存储上传的编译产物。
- `jobs/pending/`：等待执行机 worker 拉取的任务。
- `jobs/running/`：已经被某个 worker claim 的任务。
- `jobs/done/`：执行成功的任务 manifest。
- `jobs/failed/`：执行失败的任务 manifest。
- `jobs/timeout/`：超时任务 manifest。
- `results/<job_id>/`：stdout、stderr、meta 和收集文件。
- `audit/events.jsonl`：任务提交、claim、结束的审计日志。

## 主模式：最小闭环

先准备一个最小 artifact：

```bash
mkdir -p /tmp/agent-remote-demo/pkg
cat >/tmp/agent-remote-demo/pkg/run_case.sh <<'EOF'
echo "hello from remote case: $1"
echo "{\"ok\": true}" > result.json
EOF
tar -czf /tmp/agent-remote-demo/op_package.tar.gz -C /tmp/agent-remote-demo/pkg .
```

提交任务：

```bash
python -m agent_remote.cli --relay-root .agent-remote/relay submit \
  --target exec-a \
  --artifact /tmp/agent-remote-demo/op_package.tar.gz \
  --cmd "sh run_case.sh case_001" \
  --collect "result.json" \
  --collect "*.log" \
  --json
```

输出会包含 `job_id`：

```json
{
  "artifact_sha256": "...",
  "job_id": "job-20260512T000000Z-12345678",
  "ok": true,
  "status": "PENDING",
  "target": "exec-a"
}
```

执行机 worker 跑一次。真实部署时通常让 worker 长期运行，`--once` 只用于本机验证或调试：

```bash
python -m agent_remote.cli --relay-root .agent-remote/relay worker \
  --target exec-a \
  --work-root .agent-remote/worker \
  --once \
  --json
```

查询状态：

```bash
python -m agent_remote.cli --relay-root .agent-remote/relay status <job_id>
python -m agent_remote.cli --relay-root .agent-remote/relay status <job_id> --json
```

查看日志：

```bash
python -m agent_remote.cli --relay-root .agent-remote/relay logs <job_id>
python -m agent_remote.cli --relay-root .agent-remote/relay logs <job_id> --stderr
python -m agent_remote.cli --relay-root .agent-remote/relay logs <job_id> --tail 100
```

拉取结果：

```bash
python -m agent_remote.cli --relay-root .agent-remote/relay fetch \
  <job_id> \
  --out ./results/<job_id>
```

结果目录示例：

```text
results/<job_id>/
  stdout.log
  stderr.log
  meta.json
  tree.txt
  collected/
    result.json
```

## 主模式：Windows PC 中转

当编译机和执行机无法互通，但两者都能访问 Windows PC 时，推荐使用 Windows 作为 relay。这是 relay 主模式最重要的部署形态之一。

Windows 上创建目录：

```text
C:\agent-remote\
  artifacts\
  jobs\
  results\
  audit\
```

实际使用时，Linux 上通常会通过 SMB/SFTP/sshfs/企业网盘客户端把这个目录挂载成路径。

编译机示例：

```bash
python -m agent_remote.cli --relay-root /mnt/windows/agent-remote submit \
  --target exec-a \
  --artifact ./dist/op_package.tar.gz \
  --cmd "sh run_case.sh case_001" \
  --collect "result.json" \
  --json
```

执行机长期运行 worker：

```bash
python -m agent_remote.cli --relay-root /mnt/windows/agent-remote worker \
  --target exec-a \
  --work-root /data/agent-remote/worker
```

执行机只需要主动访问 relay，不需要对编译机开放端口。这对企业内网和隔离网络更友好，也是 relay 模式优先于 SSH direct 的主要原因。

## 使用配置文件和 profile

推荐把常用目标、执行命令、收集规则和安全限制写进配置文件。示例见：

```text
examples/remote-run.config.json
```

简化版：

```json
{
  "targets": {
    "exec-a": {
      "relay_root": ".agent-remote/relay",
      "work_root": ".agent-remote/worker",
      "default_timeout_sec": 600,
      "allowed_commands": ["sh", "python3", "./run_case.sh"],
      "allowed_profiles": ["op-test"]
    }
  },
  "profiles": {
    "op-test": {
      "target": "exec-a",
      "cmd": "sh run_case.sh case_001",
      "timeout_sec": 600,
      "collect": ["*.log", "result.json", "*.profile", "core.*"],
      "env": {
        "LD_LIBRARY_PATH": "./lib"
      }
    }
  }
}
```

用 profile 提交：

```bash
python -m agent_remote.cli --config examples/remote-run.config.json submit \
  --profile op-test \
  --artifact ./dist/op_package.tar.gz \
  --json
```

worker 使用配置中的 relay、work root、命令白名单和 profile 白名单：

```bash
python -m agent_remote.cli --config examples/remote-run.config.json worker \
  --target exec-a \
  --once
```

查询时也可以通过 `--target` 从配置中解析 relay：

```bash
python -m agent_remote.cli --config examples/remote-run.config.json status \
  <job_id> \
  --target exec-a \
  --json
```

命令行参数会覆盖 profile 中的对应字段。例如临时换 case：

```bash
python -m agent_remote.cli --config examples/remote-run.config.json submit \
  --profile op-test \
  --artifact ./dist/op_package.tar.gz \
  --cmd "sh run_case.sh case_999" \
  --timeout 1200 \
  --json
```

## Worker 安全限制

worker 支持两类白名单：

- `allowed_commands`：限制允许执行的命令名。
- `allowed_profiles`：限制允许执行的 profile。

示例：

```json
{
  "targets": {
    "exec-a": {
      "allowed_commands": ["sh", "python3", "./run_case.sh"],
      "allowed_profiles": ["op-test"]
    }
  }
}
```

如果设置了 `allowed_profiles`，没有 profile 的 ad-hoc job 会被拒绝。

也可以在命令行临时增加允许命令：

```bash
python -m agent_remote.cli --relay-root .agent-remote/relay worker \
  --target exec-a \
  --allow-command sh \
  --allow-command python3
```

注意：当前白名单是第一层安全边界，不等同于完整沙箱。执行机上仍建议使用专用用户运行 worker，例如 `agent-runner`，并把工作目录限制在 `/data/agent-remote/worker`。

## 辅助模式：SSH Direct

当编译机可以直接 SSH 到执行机时，可以使用 `ssh-submit`。它不是主路径，而是一个便利入口：用 `scp/ssh` 临时把任务送到执行机的 relay 目录，运行一次 worker，再把结果拉回本地。

前提：

- 编译机可以 `ssh user@exec-a`。
- 编译机可以 `scp` 文件到执行机。
- 执行机上的 Python 能 import `agent_remote`。
- 执行机上有足够权限创建 `remote_relay_root` 和 `remote_work_root`。

配置文件示例：

```json
{
  "targets": {
    "exec-a": {
      "ssh_host": "user@exec-a",
      "ssh_port": 22,
      "remote_relay_root": "/data/agent-remote/relay",
      "remote_work_root": "/data/agent-remote/worker",
      "remote_python": "python3"
    }
  }
}
```

执行：

```bash
python -m agent_remote.cli --config examples/remote-run.config.json ssh-submit \
  --profile op-test \
  --artifact ./dist/op_package.tar.gz \
  --json
```

不使用配置文件：

```bash
python -m agent_remote.cli ssh-submit \
  --target exec-a \
  --artifact ./dist/op_package.tar.gz \
  --cmd "sh run_case.sh case_001" \
  --ssh-host user@exec-a \
  --ssh-port 22 \
  --remote-relay-root /data/agent-remote/relay \
  --remote-work-root /data/agent-remote/worker \
  --json
```

`ssh-submit` 的内部流程：

1. 在本地 relay 创建 job manifest 和 artifact。
2. 在远端创建 relay/work 目录。
3. 用 `scp` 复制 artifact 和 pending job 到执行机。
4. 用 `ssh` 在执行机上运行一次 worker。
5. 用 `scp` 把远端 results 和最终 job manifest 拉回本地 relay。

长期使用时仍建议部署常驻 worker，并通过 relay 模式提交任务。这样 AI agent 的调用路径更稳定，也更容易审计和排查。

## Artifact 规则

artifact 可以是：

- `.tar` / `.tar.gz` / 其他 tar 格式：worker 会解包。
- `.zip`：worker 会解包。
- 普通文件：worker 会复制到 package 目录。

默认命令在解包后的 package 目录里执行。

如果不想解包：

```bash
python -m agent_remote.cli --relay-root .agent-remote/relay submit \
  --target exec-a \
  --artifact ./dist/op.bin \
  --cmd "sh -c 'chmod +x op.bin && ./op.bin'" \
  --no-extract
```

## Collect 规则

`--collect` 和 profile 里的 `collect` 都是相对 package 目录的 glob：

```bash
--collect "result.json"
--collect "*.log"
--collect "**/*.profile"
--collect "core.*"
```

绝对路径会被忽略，避免 worker 误收集工作目录外的文件。

收集到的文件会出现在：

```text
results/<job_id>/collected/
```

## JSON 输出给 AI agent 使用

提交任务：

```bash
python -m agent_remote.cli --config examples/remote-run.config.json submit \
  --profile op-test \
  --artifact ./dist/op_package.tar.gz \
  --json
```

查询状态：

```bash
python -m agent_remote.cli --config examples/remote-run.config.json status \
  <job_id> \
  --target exec-a \
  --json
```

建议 AI agent 的循环是：

```text
1. 编译代码，生成 artifact。
2. 优先使用 submit 进入 relay 主模式；只有直连调试时使用 ssh-submit。
3. status --json 获取状态、exit_code、error。
4. logs --tail 200 获取关键日志。
5. fetch 拉回 collected 文件。
6. 根据结果继续修改代码。
```

## 审计日志

relay 会写：

```text
<relay-root>/audit/events.jsonl
```

每行是一个 JSON 事件：

```json
{
  "event": "job_finished",
  "time": "2026-05-12T00:00:00Z",
  "job_id": "job-...",
  "target": "exec-a",
  "status": "SUCCEEDED",
  "profile": "op-test",
  "runner_id": "exec-host:12345",
  "exit_code": 0,
  "error": null
}
```

当前事件类型：

- `job_submitted`
- `job_claimed`
- `job_finished`

## 常见问题

### worker 显示 no job

检查：

- `--relay-root` 是否和 submit 使用同一个目录。
- worker 的 `--target` 是否和 job 的 target 一致。
- job manifest 是否还在 `jobs/pending/`。

### 任务失败，exit_code 是 127

通常是命令不存在。例如 artifact 里没有 `run_case.sh`，或者命令写成了错误路径。

查看：

```bash
python -m agent_remote.cli --relay-root .agent-remote/relay logs <job_id> --stderr
```

### worker 拒绝执行 command

如果配置了 `allowed_commands`，job 的第一个 argv 必须在白名单里。

例如命令是：

```bash
sh run_case.sh case_001
```

那么白名单里需要有：

```json
"allowed_commands": ["sh"]
```

### worker 拒绝执行 profile

如果配置了 `allowed_profiles`，任务必须通过允许的 profile 提交。ad-hoc `--cmd` 任务会被拒绝。

### SSH direct 找不到 agent_remote

说明执行机上的 `remote_python` 无法 import 当前包。可以在执行机上安装：

```bash
git clone https://github.com/0tomhoyt/agent_remote.git
cd agent_remote
python3 -m pip install -e .
```

或者把 `remote_python` 指向已经配置好环境的 Python。

## 当前状态

已实现：

- filesystem relay 主模式
- execution worker
- submit/status/logs/fetch
- profile config
- command/profile allowlists
- audit log
- ssh-submit 辅助模式

计划中：

- HTTP relay backend，作为 relay 主模式的下一种后端
- 更强的失败诊断
- 多 worker 锁和 heartbeat
