# 看番陪看 Agent

一个陪你追番的小助手：**暂停时问它「这个角色之前出现过吗 / 他之前啥故事」，它只根据你已经看到的那一集为止回答，绝不剧透。**

底层混合部署（省钱优先）：
- **文本 + 视觉**：DeepSeek Flash（`deepseek-flash`，便宜且自带 Vision）
- **语音识别**：DashScope Paraformer（`paraformer-v2`，DeepSeek 没有 ASR）

---

## 目录结构

```
anime-agent/
├── start.py            # 一键启动：问看哪部番 → 自动下字幕 → 建档案 → 问答
├── fetch_subtitles.py  # 自动搜 + 下载字幕（伪射手 assrt.net）
├── build_archive.py    # 离线：字幕/台词 → 每集「剧情摘要 + 角色表」档案
├── ask.py              # 在线：暂停时提问（不剧透）
├── transcribe.py       # 语音识别（本地音频 / URL → 文字）
├── voice_ask.py        # 语音提问（录音 → 识别 → 不剧透回答）
├── api_client.py       # LLM（DeepSeek）封装：文本 + 视觉
├── config.yaml         # 配置（填 key、选模型）
├── requirements.txt
├── subtitles/<番名>/   # 按番分文件夹放字幕
└── archive/<番名>/     # 按番分文件夹存档案
```

---

## 一、安装

```powershell
cd D:\Study\anime-agent
pip install -r requirements.txt
```

## 二、拿两个 API Key

这个项目用两家服务，各需要一个 key：

1. **DeepSeek**（文本 + 看图）：https://platform.deepseek.com → 创建 key
2. **DashScope 通义千问**（语音识别）：https://bailian.console.aliyun.com → 创建 key

把两个 key 写进环境变量（推荐）：

```powershell
setx DEEPSEEK_API_KEY "sk-你的deepseek-key"
setx DASHSCOPE_API_KEY "sk-你的dashscope-key"
# 设完重启终端才生效
```

或者直接编辑 `config.yaml`，在 `llm` 和 `asr` 两段里分别填 `api_key`。

---

## 三、三步跑起来（阶段一：核心链路）

### 0. 先自检（不联网、不花 API 钱）

```powershell
python selftest.py
```

它会用一个假模型把「解析 → 建档案 → 汇总 → 不剧透问答」整条链路跑一遍，验证解析器、剧透锁、提示词组装这些纯逻辑部分对不对。全绿再往下走。

### 1. 准备字幕

把每一集的字幕文件放进 `subtitles/` 文件夹，命名成 `EP01.ass`、`EP02.ass`……（`.srt` 也行）。

> 拿不到字幕？B站是硬字幕/DRM，网上通常能搜到现成外挂字幕（伪射手 assrt.net、字幕库、SubHD、动漫花园）。
> 实在没有，就录下音频走 `transcribe.py` 转成文字（见下面「语音识别」）。

### 2. 生成剧情档案

```powershell
python build_archive.py subtitles
```

它会逐集调用 LLM，生成 `archive/EP01.json`、`EP02.json`……每份里是「剧情摘要 + 本集出场角色表」。

### 3. 提问（不剧透）

```powershell
# 只知道长啥样 → 给截图让它认人
python ask.py --episode 5 --image shot.png --question "这个红头发女生之前出现过吗"

# 知道名字 → 直接问
python ask.py --episode 5 --character 鸣人 --question "鸣人前面经历了什么"
```

它会**只检索第 1~5 集**的档案来回答，后面的剧情它碰都不碰。

---

## 四、语音识别（阶段二）

`transcribe.py` 用的是 Paraformer 录音文件识别。**现在直接喂本地文件就行**——它会自动把文件上传到 DashScope 的临时存储（免费，48 小时有效），再识别，不用你搭 OSS。

```powershell
# 本地音频文件（自动上传）
python transcribe.py EP01.mp3 --out 台词.txt

# 也支持直接给公网 URL
python transcribe.py https://你的音频地址.mp3 --out 台词.txt
```

两种用法：

1. **番剧音频 → 台词**：转出来的文字，当字幕一样喂给 `build_archive.py` 建档案。
2. **你的语音 → 问题**：直接跑 `voice_ask.py`，按住说话 → 自动转文字 → 不剧透回答。

```powershell
# 语音提问（需要麦克风 + pip install sounddevice numpy）
python voice_ask.py --episode 5
```

> 进阶提示：Paraformer 支持 `diarization_enabled: true`（区分不同说话人）、`language_hints: ["ja"]`（日语番），都在这份脚本的 `parameters` 里改。

---

## 五、不剧透是怎么做到的（三道锁）

1. **数据层**：`ask.py` 只加载 `EP01` 到 `EP{当前集}` 的档案，后面的根本进不了它的视野；
2. **提示词层**：系统提示写死"你的世界截止到第 N 集，只准用档案，禁止补充、禁止暗示"；
3. **对抗模型自带剧透**：提示词里强约束"禁止调用你自己的记忆"。对火出圈的番，模型可能背过剧情，这是已知难点，后续可以再收紧。

---

## 六、一键启动 + 自动下字幕

`start.py` 把流程串起来：**上来先问你今天看哪部番、看到第几集**，本地没字幕就自动用伪射手（assrt.net）搜 + 下载，再建档案，最后进入问答。

```powershell
python start.py
```

自动下字幕依赖 assrt 的 token（免费）：

1. 去 https://assrt.net 注册；
2. 在「用户面板」复制 API Token；
3. 填进 `config.yaml` 的 `subtitle.api_key`（或设环境变量 `ASSRT_TOKEN`）。

也可以单独手动搜字幕：

```powershell
python fetch_subtitles.py "葬送的芙莉莲" --anime 芙莉莲
```

下载后按番名分文件夹存放：`subtitles/<番名>/`、`archive/<番名>/`，今天看 A、明天看 B 互不干扰。

> 说明：自动下载是"尽力而为"——assrt 上没有的番（尤其国漫/冷门/新番）会退回让你手动放字幕。字幕资源由 assrt.net 提供。

---

## 七、下一步（待做）

- [x] 本地音频上传（已完成：`transcribe.py` 自动上传临时存储，无需 OSS）
- [x] 语音提问（已完成：`voice_ask.py`，录音 → ASR → ask 自动串起来）
- [x] 自动下字幕 + 一键启动（`fetch_subtitles.py` + `start.py`）
- [ ] 按角色做索引/向量检索（集数多了以后更快更准）
- [ ] 网页界面
