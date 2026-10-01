"""
build_archive.py —— 离线预处理：把每一集的字幕（.srt / .ass）解析成文本，
再调用 LLM 生成「剧情摘要 + 出场角色表」，存成 archive/EPxx.json。

用法：
    python build_archive.py subtitles
    python build_archive.py EP01.srt EP02.srt
"""
import os
import re
import sys
import json
import argparse

from api_client import load_config, chat_text

# 让中文正常打印（Windows 控制台）
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ---------------- 字幕解析 ----------------

def parse_srt(text):
    lines = []
    for block in re.split(r"\n\s*\n", text.strip()):
        parts = [p.strip() for p in block.split("\n") if p.strip()]
        # 去掉序号行和时间行（形如 00:00:01,000 --> 00:00:04,000）
        parts = [p for p in parts if not re.match(r"^\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s*-->", p)]
        parts = [p for p in parts if not p.isdigit()]
        lines.extend(parts)
    return "\n".join(lines)


def parse_ass(text):
    lines = []
    in_events = False
    for raw in text.splitlines():
        if raw.startswith("[Events]"):
            in_events = True
            continue
        if raw.startswith("[") and not raw.startswith("[Events]"):
            in_events = False
            continue
        if in_events and raw.startswith("Dialogue:"):
            # Dialogue 行有 9 个逗号，最后一段是台词
            parts = raw.split(",", 9)
            if len(parts) == 10:
                content = parts[9]
                content = re.sub(r"\{[^}]*\}", "", content)      # 去掉 {\xxx} 样式
                content = content.replace("\\N", "\n").replace("\\n", "\n")
                content = content.strip()
                if content:
                    lines.append(content)
    return "\n".join(lines)


def parse_subtitle(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        text = f.read()
    ext = os.path.splitext(path)[1].lower()
    if ext == ".srt":
        return parse_srt(text)
    if ext in (".ass", ".ssa"):
        return parse_ass(text)
    raise ValueError(f"不支持的字幕格式：{ext}（只支持 .srt / .ass / .ssa）")


# ---------------- LLM 提取 ----------------

JSON_SPEC = '''{
  "summary": "用 2~3 句话概括本集剧情",
  "characters": [
    {"name": "角色名", "appearance": "本集里这个角色做了什么（一句话）"}
  ]
}'''

EXTRACT_PROMPT_HEAD = '''下面是第 {ep} 集动画的字幕文本。请完成两件事，并且【只输出一个 JSON】，不要输出任何解释文字，不要用 markdown 代码块包裹：

{json_spec}

要求：
1. characters 里只列本集【真正出场】且有台词或明显行动的角色，不要列只是被提到的名字。
2. 角色名用作品里的常用称呼，同一人在每一集都要用同一个名字。
3. 严格按照上面的 JSON 结构输出。

字幕文本：
'''


def parse_json(raw):
    raw = raw.strip()
    raw = re.sub(r"^```(json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"模型没输出合法 JSON，前 200 字：{raw[:200]}")
    return json.loads(raw[start:end + 1])


def build_episode(cfg, subtitle_text, ep):
    prompt = EXTRACT_PROMPT_HEAD.format(ep=ep, json_spec=JSON_SPEC) + subtitle_text
    raw = chat_text(cfg, [{"role": "user", "content": prompt}])
    return parse_json(raw)


def guess_episode(filename, fallback):
    """从文件名猜集数：EP01 / 第01话 / 第01集 / 01。"""
    m = re.search(r"EP\s*(\d+)", filename, re.I) or \
        re.search(r"第\s*(\d+)\s*[话集回]", filename) or \
        re.search(r"(\d{1,3})\s*\.(srt|ass|ssa)$", filename, re.I)
    if m:
        return int(m.group(1))
    return fallback


def collect_files(inputs):
    files = []
    for inp in inputs:
        if os.path.isdir(inp):
            for fn in sorted(os.listdir(inp)):
                if fn.lower().endswith((".srt", ".ass", ".ssa")):
                    files.append(os.path.join(inp, fn))
        else:
            files.append(inp)
    return files


def main():
    ap = argparse.ArgumentParser(description="字幕 -> 剧情档案")
    ap.add_argument("inputs", nargs="+", help="字幕文件或文件夹")
    ap.add_argument("--episode", type=int, default=None, help="指定集数（单文件时用）")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--anime", default=None, help="番名，档案存到 archive/<番名>/")
    args = ap.parse_args()

    cfg = load_config(args.config)
    anime = args.anime or cfg.get("anime", "default")
    archive_dir = os.path.join(cfg.get("paths", {}).get("archive", "archive"), anime)
    os.makedirs(archive_dir, exist_ok=True)

    files = collect_files(args.inputs)
    if not files:
        print("没找到字幕文件。请确认路径里有没有 .srt / .ass 文件。")
        return

    for i, f in enumerate(files, 1):
        ep = args.episode if (args.episode and len(files) == 1) else guess_episode(f, i)
        text = parse_subtitle(f)
        print(f"→ 第 {ep} 集《{os.path.basename(f)}》{len(text)} 字，提取中……")
        data = build_episode(cfg, text, ep)
        data["episode"] = ep
        out = os.path.join(archive_dir, f"EP{ep:02d}.json")
        with open(out, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        print(f"   已保存 → {out}")

    print("\n完成！下一步运行 ask.py 提问。")


if __name__ == "__main__":
    main()
