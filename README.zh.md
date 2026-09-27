<div align="center">

# ⬦ Perslis Floor

### 基于你自己的数据，给出精确答案。推理环节不调用模型。

对你的数据提出一次问题，得到一个**经过签名的工具**，你的 AI 助手此后可以随时调用：
离线、免费、精确；数据不足以支撑精确答案时，它会**拒绝回答，而不是猜测**。

[English](README.md) · 中文

</div>

---

## 安装

**经过验证的安装**：在签名核对通过之前，不运行任何代码。先下载安装脚本与签名的校验和，用 Perslis 发布密钥验证，再运行安装脚本；安装脚本会下载压缩包、再次验证、解压到 `~/perslis-floor` 并运行演示：

```bash
V=1.1.2; B=https://github.com/AgewellEPM/perslis-floor/releases/download/v$V
curl -fsSL -O "$B/install.sh" -O "$B/SHA256SUMS" -O "$B/SHA256SUMS.sig"
echo 'releases@perslis.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJfmXcRm2o52skHrajOCntbGMwPIB13CWnzt/tRGxXxd' > perslis_signers
ssh-keygen -Y verify -f perslis_signers -I releases@perslis.com -n perslis-release -s SHA256SUMS.sig < SHA256SUMS
grep ' install.sh$' SHA256SUMS | shasum -a 256 -c -
bash install.sh
```

我们不提供 `curl … | bash` 形式的命令：从某个分支直接管道执行脚本，会在任何验证之前就运行该分支上的内容。

**或手动安装**：从[最新发行版](https://github.com/AgewellEPM/perslis-floor/releases/latest)下载 `perslis-floor-1.1.2.zip`、`SHA256SUMS` 与 `SHA256SUMS.sig`，验证后再解压：

```bash
ssh-keygen -Y verify -f perslis_signers -I releases@perslis.com -n perslis-release -s SHA256SUMS.sig < SHA256SUMS
grep ' perslis-floor-1.1.2.zip$' SHA256SUMS | shasum -a 256 -c -
unzip perslis-floor-1.1.2.zip && cd perslis-floor-1.1.2
```

同一把发布公钥也公布在 [perslis.com/perslis-floor](https://perslis.com/perslis-floor.zh)。请对照两处：只出现在一个地方的密钥证明不了任何事。
压缩包内每个文件都列在 `MANIFEST.sha256` 中（`shasum -a 256 -c MANIFEST.sha256`）。

## 60 秒演示

下载包附带虚构的发票与供应商数据，以及六个经过准入、以独立计算结果核对审核并签名的工具：

```bash
python3 floor-serve.py --data demo/data --tools demo/tools --check
```

连接到 Claude Code，用自然语言提问：

```bash
claude mcp add perslis-floor-demo -- python3 "$PWD/floor-serve.py" \
    --data "$PWD/demo/data" --tools "$PWD/demo/tools"
```

> *“我们在各供应商区域分别付了多少钱？”*

Claude 调用工具，得到精确答案，以及生成它的计算流程：

```json
{"status": "DERIVED", "value": {"Central": 11215.45, "East": 21576.59, "South": 4800.25, "West": 32996.02},
 "model_calls": 0,
 "derivation": "rows -> filter(status equals 'paid') -> join(vendors on vendor_id=id) -> group_by(vendors.region) -> sum(amount)"}
```

问一个没有工具能回答的问题（*“我们的客户流失率是多少？”*），它会如实说明，并在你的机器上记录这个问题，而不会编造数字。

## 工作方式

1. **模型编写规格，而非代码。** 它从封闭的词汇表中组合流水线：`rows → filter → join → group_by → sum`。没有通往 Python 的逃生口。
2. **准入关卡证明它。** 列真实存在；数据足以支撑精确答案；结果确定；验证器必须*拒绝*错误答案；无证据时弃权；数据变化时答案随之变化——因此不可能是模型记住的常数。
3. **由人批准。** 关卡能证明规格“按其写法”是正确的，却无法证明它“表达的正是问题的含义”（一个“已付款总额”却筛选 `status == 'open'` 的规格能通过所有机械检查）。因此审核人会阅读工具计算内容的文字说明及其在真实数据上的答案；这份批准由审核人自己的密钥签名，运行时会拒绝任何缺少有效批准的工具。
4. **在你的机器上运行。** 运行时验证 Ed25519 签名，并通过 MCP 提供工具。每个答案都带有 `model_calls: 0` 与推导过程。

## 它不会做什么

- **猜测。** 无证据返回 `NO_EVIDENCE`；无匹配行返回 `NO_VALUE`。
- **基于不可信的数据作答。** 数值列中的 `N/A`、日期列中的 `03/04/2026`（三月还是四月？）、重复出现的关联键（会重复计数）、无法匹配的行（会静默漏算）、损坏的 JSON 行、正在写入的文件——一律返回 `REFUSED` 并说明原因。
- **运行 Perslis 未准入的工具。** 修改一个已签名的工具，运行时会点名拒绝它，其余工具照常服务。运行时只持有公钥：它能验证签名，却无法生成签名。这是对你的保证，而不是针对你的锁——源码就在这里。
- **向外联网。** `grep -rnE "socket|urllib|http|requests" floor_runtime/` 找不到任何结果。本地日志分为可分享的 `tools/logs/`（不含数值、不含问题文本）与属于你的 `tools/private/`。

## 为你的数据获取工具

准入关卡与签名密钥保留在 Perslis，这是有意为之：一个被错误签名的工具会自信地、离线地、永久地给出答案，而再也没有任何环节去复查它。目前的试点流程是：你发送数据导出与问题，我们构建每个工具、逐一审核并签名，你得到一个工具包（本运行时、你的工具与一份指南）。

→ **[perslis.com/contact](https://perslis.com/contact.zh.html)**

## 状态

**试点版 · 1.1.2。** 在 Python 3.9（macOS 默认版本）与 3.13 上端到端测试，包括真实 MCP 客户端调用构建好的工具包。
在 M 系列笔记本上以 50 万行（18 MB CSV）实测：加载约 1.3 秒，内存约 400 MB，数据变化后的首次查询约 2.3 秒，重复查询即时返回。
已知限制：不支持相对日期（“最近 30 天”）；不支持带参数的工具（每个问题一个工具）；数据在内存中处理，默认上限 100 万行；不直接连接数据库——请导出为 CSV 或 SQLite。

## 许可

源码可见（source-available）。可免费使用，包括商业用途，用于运行经 Perslis 准入的工具；不得将修改后的副本冒充为 Perslis 运行时，也不得声称某个规格已被准入而实际并未准入。准入关卡不包含在内。见 [`LICENSE.txt`](LICENSE.txt)。
