# ms2hf-sync

用 **GitHub Actions** 在 ModelScope 与 HuggingFace 之间**免代理**同步模型/数据集仓库。

```
本地(国内) ──直连上传──> ModelScope ──GitHub runner 中转──> HuggingFace
                                     ↑ 这一段走 GitHub 服务器带宽，
                                       不占本地流量、不需要代理
```

适合场景：国内网络直连 HuggingFace 困难，想把几十 GB 的模型发布到 HF；先把模型传到国内直连的 ModelScope，再让 GitHub 的机器替你把文件搬到 HF。反向（HF→MS）同样支持。

## 工作原理

底层调用 [`ms2hf`](https://github.com/pkufool/ms2hf)（PyPI 同名包）——逐文件中继：

```
循环: 从源平台下载一个文件 → 上传到目标平台 → 删除本地文件 → 下一个
```

- **逐文件处理**，磁盘峰值 ≈ 并发数 × 最大单文件（不是整个仓库）
- **目标已存在的同路径文件自动跳过** → 天然断点续传，任务挂了重跑即可
- 模型（model）和数据集（dataset）仓库都支持
- workflow 只用官方 CLI（`ms2hf`），token 不经过任何第三方 Action 代码

## 前置条件

| 项目 | 获取位置 | 要求 |
|---|---|---|
| `HF_TOKEN` | huggingface.co → Settings → Access Tokens | **write** 权限 |
| `MS_TOKEN` | modelscope.cn → 个人中心 → 访问令牌 | SDK/API token |
| 源仓库 | 任一平台 | 文件已在源侧（public 或 token 可读） |

## 配置（一次性，2 分钟）

仓库 → **Settings → Secrets and variables → Actions** → New repository secret，添加：

- `HF_TOKEN`
- `MS_TOKEN`

（也可以终端 `gh secret set HF_TOKEN -R <owner>/ms2hf-sync`，回车后粘贴）

## 使用

**Actions → ms2hf-sync → Run workflow**，四个参数：

| 参数 | 说明 | 默认值 |
|---|---|---|
| `direction` | `ms2hf` = MS→HF；`hf2ms` = HF→MS | `ms2hf` |
| `source_repo` | 源仓库 `owner/name`（方向决定平台） | `terry2010/Huihui-Ornith-1.5-35B-A3B-oQ4e-mtp` |
| `target_repo` | 目标仓库 `owner/name` | `terry2010/Ornith-1.5-35B-A3B-abliterated-MLX-oQ4e-mtp` |
| `repo_type` | `model` 或 `dataset` | `model` |

默认值是本仓库作者当前的同步任务，**换仓库直接改输入框即可**，不用改代码。

运行中可以在 job 日志里实时看每个文件的下载/上传进度。已存在的文件会被跳过，所以重复触发 = 增量补传。

## 限制与注意

| 项 | 限制 | 说明 |
|---|---|---|
| runner 磁盘 | ~14 GB | workflow 用 `--workers 2`，峰值 ≈ 2×最大单文件。**单文件 >6GB 请把 `--workers` 改成 1** |
| 单 job 时长 | 6 h | 超时后重跑，已传文件自动跳过 |
| 并发提交 | HF 侧串行 | 多个 job 同时往同一 HF 仓库推可能产生提交冲突，建议一次只跑一个同步（`concurrency` 已按方向+源仓锁定） |
| token 安全 | repo secrets | 不要把 token 写进 workflow 文件或日志；public 仓的 secrets 对 fork PR 不暴露，但 workflow 修改权限要谨慎分发 |
| 大仓预算 | public 免费 | public repo Actions 不限时；private 每月 2000 分钟免费额度 |

## 常见问题

**Q: 目标仓库需要先建好 README 吗？**
不需要，ms2hf 只写文件。但 HF 侧建议先放好 `README.md`（模型卡）——文件到齐前页面对外是骨架状态。

**Q: ModelScope 建仓时报「名称含有敏感内容」？**
MS 对仓库名有审核词表（如 `abliterated`），换个中性名字即可，不影响文件内容。

**Q: 进度卡住不动？**
看日志定位是下载段（MS）慢还是上传段（HF）慢；MS 侧在凌晨通常更快。直接重跑同一个 workflow，已完成的文件会跳过。

**Q: 想定时自动同步？**
在 `on:` 里加 schedule（cron），注意两个平台的源/目标会按方向互换。

## 文件说明

```
.github/workflows/ms2hf.yml   手动触发的同步 workflow（全部逻辑都在这）
README.md                     本文件
```

## License

MIT
