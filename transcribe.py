"""
transcribe.py —— 语音识别（云 API / Paraformer）。
把音频转成文字，用于：
  1) 番剧音频 → 台词（当拿不到字幕时，喂给 build_archive.py 建档案）
  2) 你的语音 → 问题（喂给 ask.py）

支持两种输入：
  - 本地音频文件（自动上传到 DashScope 临时存储，无需自己搭 OSS）
  - 公网 URL / oss:// 地址

用法：
    python transcribe.py 你的音频.mp3
    python transcribe.py https://你的音频地址.mp3
"""
import os
import sys
import time
import json
import argparse

import requests
from api_client import load_config, get_key

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def upload_local_file(cfg, file_path, model=None):
    """把本地文件上传到 DashScope 临时存储，返回 oss:// 地址（48 小时有效）。

    注意：上传时要指定「会用这个文件的模型」，后续调用要用同一个模型。
    """
    sec = cfg["asr"]
    key = get_key(sec)
    model = model or sec.get("model", "paraformer-v2")
    base = sec.get("base_url", "https://dashscope.aliyuncs.com").rstrip("/")

    # 1) 拿上传凭证
    cred = requests.get(
        base + "/api/v1/uploads",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        params={"action": "getPolicy", "model": model},
        timeout=30,
    )
    cred.raise_for_status()
    data = cred.json()["data"]

    # 2) 上传文件（file 字段必须放最后）
    fname = os.path.basename(file_path)
    obj_key = f"{data['upload_dir']}/{fname}"
    with open(file_path, "rb") as f:
        up = requests.post(
            data["upload_host"],
            files={
                "OSSAccessKeyId": (None, data["oss_access_key_id"]),
                "Signature": (None, data["signature"]),
                "policy": (None, data["policy"]),
                "x-oss-object-acl": (None, data["x_oss_object_acl"]),
                "x-oss-forbid-overwrite": (None, data["x_oss_forbid_overwrite"]),
                "key": (None, obj_key),
                "success_action_status": (None, "200"),
                "file": (fname, f),
            },
            timeout=120,
        )
        up.raise_for_status()

    return f"oss://{obj_key}"


def transcribe_local(cfg, file_path, language_hints=None):
    """本地音频 → 上传临时存储 → 识别。省去手动传 OSS。"""
    url = upload_local_file(cfg, file_path)
    print(f"已上传临时存储：{url}")
    return transcribe_url(cfg, url, language_hints=language_hints)


def transcribe_url(cfg, audio_url, language_hints=None, max_wait=600):
    sec = cfg["asr"]
    key = get_key(sec)
    base = sec.get("base_url", "https://dashscope.aliyuncs.com").rstrip("/")
    hints = language_hints or sec.get("language_hints", ["zh", "en"])

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
        "X-DashScope-OssResourceResolve": "enable",  # 让 oss:// 临时地址能被解析
    }
    body = {
        "model": sec.get("model", "paraformer-v2"),
        "input": {"file_urls": [audio_url]},
        "parameters": {
            "channel_id": [0],
            "language_hints": hints,
            "disfluency_removal_enabled": True,      # 去掉语气词
            "timestamp_alignment_enabled": False,
        },
    }

    submit_url = base + "/api/v1/services/audio/asr/transcription"
    r = requests.post(submit_url, headers=headers, json=body, timeout=30)
    r.raise_for_status()
    task_id = r.json()["output"]["task_id"]
    print(f"已提交任务：{task_id}")

    task_url = base + f"/api/v1/tasks/{task_id}"
    waited = 0
    while waited < max_wait:
        time.sleep(5)
        waited += 5
        q = requests.get(task_url, headers={"Authorization": f"Bearer {key}"}, timeout=30)
        q.raise_for_status()
        out = q.json()["output"]
        status = out.get("task_status")
        if status == "SUCCEEDED":
            result = out["results"][0]
            if result.get("subtask_status") != "SUCCEEDED":
                raise RuntimeError(f"识别失败：{result}")
            turl = result["transcription_url"]
            tr = requests.get(turl, timeout=30).json()
            texts = [t.get("text", "") for t in tr.get("transcripts", [])]
            return {"full_text": "\n".join(texts), "raw": tr}
        if status in ("FAILED", "CANCELED", "UNKNOWN"):
            raise RuntimeError(f"任务失败：{out}")
        print(f"  处理中……已等 {waited}s")
    raise TimeoutError("识别超时（音频太长或排队太久）")


def main():
    ap = argparse.ArgumentParser(description="Paraformer 语音识别（支持本地文件或 URL）")
    ap.add_argument("audio", help="本地音频路径，或 http(s)/oss:// 音频地址")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--out", default=None, help="把识别文本保存到文件（可选）")
    args = ap.parse_args()

    cfg = load_config(args.config)

    if args.audio.startswith(("http://", "https://", "oss://")):
        result = transcribe_url(cfg, args.audio)
    else:
        if not os.path.exists(args.audio):
            print(f"文件不存在：{args.audio}")
            return
        result = transcribe_local(cfg, args.audio)

    print("\n——识别结果——\n")
    print(result["full_text"])

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(result["full_text"])
        print(f"\n已保存 → {args.out}")


if __name__ == "__main__":
    main()
