"""
fetch_subtitles.py —— 用伪射手 assrt.net API 自动搜索并下载字幕。

流程：search 搜番名 → 挑一个最像的（优先 srt/ass、简体、评分高）→
      detail 拿下载地址 → 下载到 subtitles/<番名>/

用法：
    python fetch_subtitles.py "葬送的芙莉莲" --anime 芙莉莲

字幕资源由 assrt.net 提供（个人免费，需注册拿 Token）。
"""
import os
import sys
import zipfile
import argparse

import requests
from api_client import load_config, get_key

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def search(cfg, query, cnt=15):
    sec = cfg["subtitle"]
    base = sec.get("api_base", "https://api.assrt.net").rstrip("/")
    r = requests.get(
        f"{base}/v1/sub/search",
        params={"token": get_key(sec), "q": query, "cnt": cnt},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("status") != 0:
        raise RuntimeError(f"搜索失败：{data}")
    return data["sub"]["subs"]


def detail(cfg, sub_id):
    sec = cfg["subtitle"]
    base = sec.get("api_base", "https://api.assrt.net").rstrip("/")
    r = requests.get(
        f"{base}/v1/sub/detail",
        params={"token": get_key(sec), "id": sub_id},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("status") != 0:
        raise RuntimeError(f"获取详情失败：{data}")
    return data["sub"]["subs"][0]


def _score(sub):
    """给一条字幕打分：srt/ass > 其它格式；简体/中文 > 其它；评分越高越好。"""
    s = 0.0
    t = (sub.get("subtype") or "").lower()
    if "srt" in t or "ass" in t:
        s += 10
    desc = sub.get("lang", {}).get("desc") or ""
    if "简" in desc or "中" in desc:
        s += 5
    s += min(sub.get("vote_score", 0), 20) / 20.0
    return s


def pick_best(subs):
    """从搜索结果里挑最合适的一条。"""
    return max(subs, key=_score) if subs else None


def _download(url, dest):
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    with open(dest, "wb") as f:
        f.write(r.content)
    return dest


def _extract_zip(zip_path, outdir):
    """从 zip 里抽出第一个 .srt/.ass 文件，返回路径（没有则返回 None）。"""
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if name.lower().endswith((".srt", ".ass", ".ssa")):
                dest = os.path.join(outdir, os.path.basename(name))
                with open(dest, "wb") as f:
                    f.write(z.read(name))
                return dest
    return None


def auto_fetch(cfg, query, outdir):
    """搜一个番名，下载最匹配的字幕到 outdir。返回保存的文件路径列表。"""
    subs = search(cfg, query)
    if not subs:
        return []
    best = pick_best(subs)
    d = detail(cfg, best["id"])

    saved = []
    # 优先用 filelist 里独立的 .srt/.ass（不用解压）
    files = [f for f in d.get("filelist", [])
             if (f.get("f") or "").lower().endswith((".srt", ".ass", ".ssa"))]
    if files:
        dest = os.path.join(outdir, files[0]["f"])
        _download(files[0]["url"], dest)
        return [dest]

    # 否则下载整个包
    url = d.get("url")
    if not url:
        return []
    fname = d.get("filename") or "sub.zip"
    tmp = os.path.join(outdir, fname)
    _download(url, tmp)

    if fname.lower().endswith(".zip"):
        got = _extract_zip(tmp, outdir)
        os.remove(tmp)
        return [got] if got else []
    if fname.lower().endswith(".rar"):
        print(f"   ⚠ 下载的是 rar 压缩包，请手动解压：{tmp}")
        return []
    return [tmp]      # 直接就是字幕文件


def main():
    ap = argparse.ArgumentParser(description="自动搜索并下载番剧字幕（assrt.net）")
    ap.add_argument("query", help="番名（搜索关键词）")
    ap.add_argument("--anime", default=None, help="存到 subtitles/<anime>/；默认用 query")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    anime = args.anime or args.query
    outdir = os.path.join(cfg["paths"]["subtitles"], anime)
    os.makedirs(outdir, exist_ok=True)

    print(f"搜索「{args.query}」……")
    try:
        saved = auto_fetch(cfg, args.query, outdir)
    except Exception as e:
        print(f"❌ 自动下载失败：{e}")
        print("   可以手动去字幕站下载后放进：", outdir)
        return

    if saved:
        print(f"✅ 已下载 {len(saved)} 个文件到 {outdir}")
        for s in saved:
            print("   ", s)
    else:
        print("❌ 没找到合适字幕。换个关键词试试，或手动下载放进：", outdir)


if __name__ == "__main__":
    main()
