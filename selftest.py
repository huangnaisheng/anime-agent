"""
selftest.py —— 离线自检（不联网、不花 API 钱）：
用一个"假模型"把「建档案 → 汇总 → 不剧透问答」整条链路跑一遍，
验证解析器、剧透锁、提示词组装这些纯逻辑部分是否正确。

用法：python selftest.py
"""
import sys
import os
import json
import tempfile

sys.stdout.reconfigure(encoding="utf-8")

import api_client as ac
import build_archive as ba
import ask
import transcribe
import fetch_subtitles

# ---------- 构造假 LLM（拦截所有网络调用） ----------
LAST_MESSAGES = {}


class _Msg:
    def __init__(self, c):
        self.content = c


class _Choice:
    def __init__(self, c):
        self.message = _Msg(c)


class _Resp:
    def __init__(self, c):
        self.choices = [_Choice(c)]


class _Completions:
    def create(self, **kw):
        msgs = kw["messages"]
        LAST_MESSAGES["messages"] = msgs
        user = msgs[-1]["content"]
        if isinstance(user, list):
            user = " ".join(p.get("text", "") for p in user if p.get("type") == "text")
        if "字幕文本" in user:
            # 模拟 build_episode 时模型返回的（带 markdown 围栏的）JSON
            return _Resp('```json\n{"summary":"主角遇到红发少女","characters":[{"name":"红发少女","appearance":"帮主角挡了一刀"}]}\n```')
        return _Resp("出现过，第 2 集他帮主角挡了一刀。")


class _Chat:
    def __init__(self):
        self.completions = _Completions()


class _Client:
    def __init__(self):
        self.chat = _Chat()


ac.llm_client = lambda cfg: _Client()


def base_cfg(archive_dir):
    return {
        "llm": {"api_key": "sk-test", "model": "deepseek-flash",
                "base_url": "https://api.deepseek.com", "thinking": False},
        "asr": {"api_key": "sk-test", "model": "paraformer-v2",
                "base_url": "https://dashscope.aliyuncs.com"},
        "anime": "测试番",
        "paths": {"archive": archive_dir},
    }


# ---------- 1. JSON 解析 ----------
print("1) parse_json（带围栏 / 带废话）")
assert ba.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
assert ba.parse_json('好的，如下：\n{"a": 1}\n希望有帮助') == {"a": 1}
print("   ✅ 通过")

# ---------- 2. 建档案 ----------
print("2) build_episode（假模型）")
cfg = base_cfg(tempfile.mkdtemp())
data = ba.build_episode(cfg, "字幕：你好", 1)
assert data["summary"] and data["characters"][0]["name"] == "红发少女"
print("   ✅ 通过 ->", json.dumps(data, ensure_ascii=False))

# ---------- 3. 档案汇总 ----------
print("3) archive_to_text")
eps = [
    {"episode": 1, "summary": "s1", "characters": [{"name": "A", "appearance": "x"}]},
    {"episode": 2, "summary": "s2", "characters": [{"name": "B", "appearance": "y"}]},
]
txt = ask.archive_to_text(eps)
assert "第 1 集" in txt and "第 2 集" in txt
print("   ✅ 通过")

# ---------- 4. 剧透锁（数据层）：只加载 ≤ 当前集 ----------
print("4) 剧透锁：看到第 3 集时只加载 1~3")
tmp = tempfile.mkdtemp()
anime_sub = os.path.join(tmp, "测试番")
os.makedirs(anime_sub, exist_ok=True)
for i in range(1, 7):
    with open(os.path.join(anime_sub, f"EP{i:02d}.json"), "w", encoding="utf-8") as f:
        json.dump({"episode": i, "summary": f"第{i}集剧情", "characters": []}, f, ensure_ascii=False)
cfg2 = base_cfg(tmp)
loaded = ask.load_archive(cfg2, 3, anime="测试番")
assert [e["episode"] for e in loaded] == [1, 2, 3]
print("   ✅ 通过，加载的集数 =", [e["episode"] for e in loaded])

# ---------- 5. 端到端问答 + 剧透锁（提示词层） ----------
print("5) answer_question 端到端 + 提示词检查")
ans = ask.answer_question(cfg2, 3, "红发少女之前出现过吗", who="红发少女", anime="测试番")
assert ans and "出现过" in ans
user_content = LAST_MESSAGES["messages"][-1]["content"]
sys_content = LAST_MESSAGES["messages"][0]["content"]
assert "第 1~3 集" in user_content
# 关键断言：第 4~6 集的剧情绝不能出现在喂给模型的内容里
for i in (4, 5, 6):
    assert f"第{i}集剧情" not in user_content, f"剧透锁被突破！第{i}集内容泄漏了"
assert "第 3 集" in sys_content
print("   ✅ 通过：第 4~6 集内容确实没有进入模型的视野")

# ---------- 6. 本地文件上传（假 requests，验证上传流程） ----------
print("6) upload_local_file（假 requests，验证上传流程）")

CAPTURED = {}


class _FakeResp:
    def __init__(self, data):
        self._data = data
        self.status_code = 200

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class _FakeRequests:
    @staticmethod
    def get(url, headers=None, params=None, timeout=None):
        CAPTURED["get_url"] = url
        CAPTURED["get_params"] = params
        return _FakeResp({"data": {
            "upload_dir": "dashscope-instant/test/2025/01/01",
            "upload_host": "https://fake-oss.example.com",
            "oss_access_key_id": "AKID",
            "signature": "SIG",
            "policy": "POL",
            "x_oss_object_acl": "private",
            "x_oss_forbid_overwrite": "true",
        }})

    @staticmethod
    def post(url, files=None, headers=None, json=None, timeout=None, data=None):
        CAPTURED["post_url"] = url
        CAPTURED["post_files"] = files
        return _FakeResp({})


transcribe.requests = _FakeRequests

tmp_audio_dir = tempfile.mkdtemp()
audio_path = os.path.join(tmp_audio_dir, "EP01.mp3")
with open(audio_path, "wb") as f:
    f.write(b"fake-audio-bytes")

cfg3 = {"asr": {"api_key": "sk-test", "model": "paraformer-v2",
                "base_url": "https://dashscope.aliyuncs.com"}}
url = transcribe.upload_local_file(cfg3, audio_path)
assert url == "oss://dashscope-instant/test/2025/01/01/EP01.mp3", url
assert CAPTURED["get_params"] == {"action": "getPolicy", "model": "paraformer-v2"}
assert CAPTURED["post_url"] == "https://fake-oss.example.com"
assert CAPTURED["post_files"]["file"][0] == "EP01.mp3"
assert CAPTURED["post_files"]["key"][1] == "dashscope-instant/test/2025/01/01/EP01.mp3"
print("   ✅ 通过：本地文件 →", url)

# ---------- 7. fetch_subtitles 选优逻辑 ----------
print("7) fetch_subtitles.pick_best（选优逻辑）")
subs = [
    {"id": 1, "subtype": "VobSub", "vote_score": 100, "lang": {"desc": "简中"}},
    {"id": 2, "subtype": "Subrip(srt)", "vote_score": 10, "lang": {"desc": "简中"}},
    {"id": 3, "subtype": "Subrip(srt)", "vote_score": 50, "lang": {"desc": "英语"}},
]
best = fetch_subtitles.pick_best(subs)
assert best["id"] == 2, best
print("   ✅ 通过：优先选 srt + 简中（id=2）")

# ---------- 8. fetch_subtitles.auto_fetch（假 requests，验证搜→详情→下载） ----------
print("8) fetch_subtitles.auto_fetch（假 requests）")


class _FakeSubResp:
    def __init__(self, data=None, content=None):
        self._data = data
        self._content = content
        self.status_code = 200

    def json(self):
        return self._data

    def raise_for_status(self):
        pass

    @property
    def content(self):
        return self._content


def _fake_sub_get(url, params=None, timeout=None):
    if "sub/search" in url:
        return _FakeSubResp(data={"status": 0, "sub": {"subs": [
            {"id": 111, "subtype": "Subrip(srt)", "vote_score": 50, "lang": {"desc": "简中"}}
        ]}})
    if "sub/detail" in url:
        return _FakeSubResp(data={"status": 0, "sub": {"subs": [
            {"id": 111, "filename": "x.rar", "url": "http://x/x.rar",
             "filelist": [{"url": "http://x/EP01.srt", "f": "EP01.srt", "s": "1KB"}]}
        ]}})
    return _FakeSubResp(content=b"1\n00:00:01,000 --> 00:00:02,000\nHello\n")


fetch_subtitles.requests = type("_FakeReq", (), {"get": staticmethod(_fake_sub_get)})()

sub_out = tempfile.mkdtemp()
outdir = os.path.join(sub_out, "测试番")
os.makedirs(outdir, exist_ok=True)
cfg_sub = {"subtitle": {"api_key": "sk-test", "api_base": "https://api.assrt.net"},
           "paths": {"subtitles": sub_out}}
saved = fetch_subtitles.auto_fetch(cfg_sub, "测试番", outdir)
assert saved and len(saved) == 1 and os.path.exists(saved[0])
with open(saved[0], "rb") as f:
    assert b"Hello" in f.read()
assert saved[0].endswith("EP01.srt")
print("   ✅ 通过：搜 → 详情 → 下载 filelist 里的 srt 并落盘")

# ---------- 9. zip 解压 ----------
print("9) fetch_subtitles._extract_zip（zip 解压）")
import zipfile
zip_dir = tempfile.mkdtemp()
zip_path = os.path.join(zip_dir, "x.zip")
with zipfile.ZipFile(zip_path, "w") as z:
    z.writestr("sub/EP01.ass", "ass content")
got = fetch_subtitles._extract_zip(zip_path, zip_dir)
assert got and os.path.basename(got) == "EP01.ass"
print("   ✅ 通过：", got)

# ---------- 10. describe_image（视觉调用结构） ----------
print("10) describe_image（视觉调用结构）")
img_path = os.path.join(tempfile.mkdtemp(), "shot.png")
with open(img_path, "wb") as f:
    f.write(b"\x89PNG fake-bytes")
cfg_img = {"llm": {"api_key": "sk-test", "model": "deepseek-flash",
                   "base_url": "https://api.deepseek.com", "thinking": False}}
out = ac.describe_image(cfg_img, img_path, "画面里有谁？")
assert out == "出现过，第 2 集他帮主角挡了一刀。"
blocks = LAST_MESSAGES["messages"][-1]["content"]
assert isinstance(blocks, list)
img_block = next(b for b in blocks if b.get("type") == "image_url")
assert img_block["image_url"]["url"].startswith("data:image/png;base64,")
print("   ✅ 通过：图片以 base64 data URL 传给视觉模型")

# ---------- 11. transcribe_url（提交 → 轮询 → 解析） ----------
print("11) transcribe_url（提交 → 轮询 → 解析结果）")


class _AsrFakeResp:
    def __init__(self, data):
        self._data = data
        self.status_code = 200

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


def _asr_post(url, headers=None, json=None, timeout=None, files=None, data=None):
    return _AsrFakeResp({"output": {"task_id": "task-123"}})


def _asr_get(url, headers=None, params=None, timeout=None):
    if "/tasks/" in url:
        return _AsrFakeResp({"output": {
            "task_status": "SUCCEEDED",
            "results": [{"subtask_status": "SUCCEEDED",
                         "transcription_url": "http://x/result.json"}],
        }})
    if "result.json" in url:
        return _AsrFakeResp({"transcripts": [{"text": "你好世界"}, {"text": "第二句"}]})
    return _AsrFakeResp({})


transcribe.requests = type("_AsrFake", (), {
    "get": staticmethod(_asr_get), "post": staticmethod(_asr_post)})()

cfg_asr = {"asr": {"api_key": "sk-test", "model": "paraformer-v2",
                   "base_url": "https://dashscope.aliyuncs.com", "language_hints": ["zh"]}}
res = transcribe.transcribe_url(cfg_asr, "https://x/audio.mp3")
assert res["full_text"] == "你好世界\n第二句", res
print("   ✅ 通过：", res["full_text"].replace("\n", " / "))

print("\n🎉 全部通过：11 项离线自检（解析/建档案/剧透锁/上传/字幕下载/视觉/ASR 解析）全部正常。")
