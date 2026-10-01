# anime-agent

一个面向追番场景的问答 Agent：基于已观看集数的字幕/台词构建逐集剧情索引，回答「某角色此前是否出现、此前发生了什么」类问题。所有回答严格限制在用户当前进度（第 1～N 集）之内，超出部分不进入模型上下文。

## 技术栈

| 组件 | 实现 | 说明 |
|---|---|---|
| 文本 / 视觉推理 | DeepSeek Flash（`deepseek-flash`） | OpenAI 兼容接口，支持视觉输入 |
| 语音识别（ASR） | DashScope Paraformer（`paraformer-v2`） | 录音文件识别 |
| 字幕检索 | assrt.net（伪射手）API | 可选，用于自动下载 |

采用低成本混合部署：文本与视觉推理全部走 DeepSeek，DashScope 仅承担 ASR（DeepSeek 不提供 ASR 能力）。

## 功能

- 字幕解析（`.srt` / `.ass`）→ 逐集生成剧情摘要与角色表
- 进度感知问答：仅加载第 1～N 集档案，后续内容不可见
- 视觉识别：传入画面截图，结合外观回答角色相关问题
- 语音识别：本地音频文件或公网 URL → 文本
- 语音提问：录音 → 识别 → 问答
- 字幕自动下载：assrt.net 检索、评分、下载、解压
- 离线自检：无网络、无 API 调用，验证核心逻辑

## 目录结构

```
anime-agent/
├── start.py            # 入口：交互式选择番剧与集数，串联下载 / 建档 / 问答
├── fetch_subtitles.py  # 字幕检索与下载（assrt.net）
├── build_archive.py    # 字幕 → 逐集档案（摘要 + 角色表）
├── ask.py              # 进度感知问答（不剧透）
├── transcribe.py       # ASR：本地文件 / URL → 文本
├── voice_ask.py        # 语音提问（录音 → 识别 → 问答）
├── api_client.py       # DeepSeek 客户端封装（文本 + 视觉）
├── config.yaml         # 配置
├── selftest.py         # 离线自检
├── requirements.txt
├── subtitles/<番名>/   # 字幕，按番剧分目录
└── archive/<番名>/     # 档案，按番剧分目录
```

## 安装

```powershell
pip install -r requirements.txt
```

语音提问（`voice_ask.py`）额外依赖 `sounddevice`，且需要麦克风。

## 配置

三组凭证，通过环境变量或 `config.yaml` 提供：

| 服务 | 用途 | 环境变量 | 申请地址 |
|---|---|---|---|
| DeepSeek | 文本 + 视觉 | `DEEPSEEK_API_KEY` | https://platform.deepseek.com |
| DashScope | 语音识别 | `DASHSCOPE_API_KEY` | https://bailian.console.aliyun.com |
| assrt.net | 字幕检索（可选） | `ASSRT_TOKEN` | https://assrt.net |

环境变量方式（推荐）：

```powershell
setx DEEPSEEK_API_KEY "sk-..."
setx DASHSCOPE_API_KEY "sk-..."
setx ASSRT_TOKEN "..."
# 重新打开终端后生效
```

也可在 `config.yaml` 对应段填写 `api_key` 字段。模型与参数（如 `llm.model`、`llm.thinking`、`asr.language_hints`）均可在配置文件中调整。

## 使用

### 1. 离线自检

```powershell
python selftest.py
```

以 mock 客户端验证解析、建档、不剧透锁定、提示词组装等纯逻辑，不产生 API 费用。

### 2. 准备字幕

将各集字幕放入 `subtitles/`（或 `subtitles/<番名>/`），命名为 `EP01.ass`、`EP02.ass`（`.srt` 亦可）。若无现成字幕，可录制音频后经 `transcribe.py` 转为文本。

### 3. 构建档案

```powershell
python build_archive.py subtitles --anime <番名>
```

逐集调用 LLM，生成 `archive/<番名>/EP01.json`（剧情摘要 + 出场角色表）。

### 4. 提问

```powershell
# 仅知外观：传入截图
python ask.py --episode 5 --image shot.png --question "这个红发角色此前是否出现" --anime <番名>

# 已知角色名：直接提问
python ask.py --episode 5 --character <角色名> --question "该角色此前经历" --anime <番名>
```

仅检索第 1～N 集档案。

### 5. 语音识别

```powershell
# 本地音频（自动上传至 DashScope 临时存储，48 小时有效）
python transcribe.py EP01.mp3 --out lines.txt

# 公网 URL
python transcribe.py https://.../audio.mp3 --out lines.txt
```

### 6. 语音提问

```powershell
python voice_ask.py --episode 5
```

番名取自 `config.yaml` 的 `anime` 字段。

### 7. 一键启动

```powershell
python start.py
```

交互式输入番剧与当前集数；本地无字幕时自动经 assrt.net 检索下载，随后建档并进入问答。

## 不剧透机制

1. **数据层**：`ask.py` 仅加载 `EP01`～`EP{current}`，后续档案不进入模型上下文。
2. **提示词层**：系统提示固定进度边界，仅允许使用档案内容回答。
3. **模型记忆抑制**：提示词约束模型不使用自身训练记忆。对热门作品仍属已知难点。

## 已知限制

- 字幕自动下载依赖 assrt.net 覆盖范围，国漫、冷门或新番可能无结果，需手动放置字幕。
- `.rar` 字幕包需手动解压。
- 模型对热门作品的先验知识可能造成剧透，需进一步约束。

## Roadmap

- [ ] 角色级索引 / 向量检索（集数增多后提升精度与速度）
- [ ] Web 界面
