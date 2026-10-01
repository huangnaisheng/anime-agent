"""
start.py —— 一键启动陪看 Agent：
  1. 上来先问：今天要看哪部番、看到第几集
  2. 本地没有该番字幕 → 自动用伪射手(assrt.net)搜 + 下载
  3. 缺档案 → 自动建剧情档案
  4. 进入问答循环（直接打字提问；输入 quit 退出）

用法：
    python start.py
"""
import os
import sys
import subprocess

from api_client import load_config
from fetch_subtitles import auto_fetch
from build_archive import collect_files
from ask import answer_question

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def build_archive(cfg, anime):
    sub = os.path.join(cfg["paths"]["subtitles"], anime)
    files = collect_files([sub]) if os.path.isdir(sub) else []
    if not files:
        return False
    print("生成剧情档案……")
    subprocess.run([sys.executable, "build_archive.py", sub, "--anime", anime],
                   check=True)
    return True


def main():
    cfg = load_config("config.yaml")

    anime = input("今天要看哪部番？").strip()
    if not anime:
        print("没输入番名，退出。")
        return
    ep_raw = input("现在看到第几集了？（直接回车默认第 1 集）").strip()
    ep = int(ep_raw) if ep_raw.isdigit() else 1

    sub_dir = os.path.join(cfg["paths"]["subtitles"], anime)
    os.makedirs(sub_dir, exist_ok=True)

    # 1) 字幕：本地没有就自动搜 + 下载
    if not collect_files([sub_dir]):
        print(f"本地还没有《{anime}》的字幕，试着自动搜索下载……")
        saved = auto_fetch(cfg, anime, sub_dir)
        if not saved:
            print("❌ 自动下载没成功。请手动把 .srt/.ass 放进：", sub_dir)
            return

    # 2) 档案：缺就建
    archive_dir = os.path.join(cfg["paths"]["archive"], anime)
    os.makedirs(archive_dir, exist_ok=True)
    if not os.path.exists(os.path.join(archive_dir, f"EP{ep:02d}.json")):
        if not build_archive(cfg, anime):
            print("没找到可用的字幕，无法建档案。")
            return

    # 3) 问答循环
    print(f"\n《{anime}》陪看开始（你看到第 {ep} 集）。")
    print("直接输入问题，输入 quit / 退出 结束。")
    while True:
        q = input("\n你问：").strip()
        if q.lower() in ("quit", "exit", "q", "退出"):
            break
        if not q:
            continue
        ans = answer_question(cfg, ep, q, anime=anime)
        if ans is None:
            print("还没有档案，先跑 build_archive.py。")
            continue
        print("\n——回答——\n" + ans)


if __name__ == "__main__":
    main()
