"""
ask.py —— 在线问答：暂停时问"某角色出现过吗 / 之前啥故事"，
只基于你已经看到的那一集为止回答，绝不剧透。

用法：
    python ask.py --episode 5 --question "这个红头发的女生之前出现过吗"
    python ask.py --episode 5 --image shot.png --question "她之前干过啥"
    python ask.py --episode 5 --character 鸣人 --question "鸣人前面经历了什么"
"""
import os
import sys
import json
import argparse

from api_client import load_config, chat_text, describe_image

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SYSTEM_PROMPT = """你是「陪我看番」助手，正在陪用户追《{anime}》。
你和用户一样，只看到第 {ep} 集（含）为止，你的世界绝对截止于此。

硬性规则（必须严格遵守）：
1. 只能依据用户提供的「已看内容档案」回答，禁止调用你自己的记忆、常识，或对这部作品后续剧情的任何了解。
2. 绝对禁止提及、暗示、预告第 {ep} 集之后的任何剧情；连"之后会有转折""这个人后面很重要"这类话都不许说。
3. 档案里没有的信息，就老实说"这个我还不清楚 / 前面还没交代"，不要编造。
4. 先直接给结论（"出现过 / 没出现过"），再简短补充相关剧情，口语化、像朋友陪聊，控制在 150 字以内。"""


def load_archive(cfg, ep, anime=None):
    root = cfg.get("paths", {}).get("archive", "archive")
    anime = anime or cfg.get("anime", "default")
    archive_dir = os.path.join(root, anime)
    content = []
    for i in range(1, ep + 1):
        p = os.path.join(archive_dir, f"EP{i:02d}.json")
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                content.append(json.load(f))
    return content


def archive_to_text(eps):
    parts = []
    for e in eps:
        chars = "\n".join(
            f"  - {c['name']}：{c.get('appearance', '')}" for c in e.get("characters", [])
        )
        parts.append(f"第 {e['episode']} 集：{e.get('summary', '')}\n角色：\n{chars}")
    return "\n\n".join(parts)


def answer_question(cfg, episode, question, who=None, anime=None):
    """核心问答逻辑（可单独调用/测试）：只基于第 1~episode 集回答。"""
    eps = load_archive(cfg, episode, anime=anime)
    if not eps:
        return None

    archive_text = archive_to_text(eps)
    sys_prompt = SYSTEM_PROMPT.format(anime=cfg.get("anime", "这部番"), ep=episode)
    user = (
        f"已看内容档案（第 1~{episode} 集）：\n\n{archive_text}\n\n"
        f"用户的问题：\n{question}\n"
        + (f"（用户画面里指向的角色：{who}）" if who else "")
    )
    return chat_text(cfg, [{"role": "system", "content": sys_prompt},
                           {"role": "user", "content": user}])


def main():
    ap = argparse.ArgumentParser(description="不剧透问答")
    ap.add_argument("--episode", type=int, required=True, help="你现在看到第几集")
    ap.add_argument("--question", required=True, help="你的问题")
    ap.add_argument("--image", default=None, help="当前画面截图（可选，帮认人）")
    ap.add_argument("--character", default=None, help="角色名（你知道的话）")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--anime", default=None, help="番名，决定读哪个档案子文件夹")
    args = ap.parse_args()

    cfg = load_config(args.config)

    who = args.character
    if args.image:
        who = describe_image(cfg, args.image, "画面里有谁？只说出角色名字或外貌特征，简短一点。")
        print(f"[视觉识别] 画面里的人 → {who}")

    answer = answer_question(cfg, args.episode, args.question, who, anime=args.anime)
    if answer is None:
        print("⚠ 没有档案。请先运行 build_archive.py 生成，再提问。")
        return

    print("\n——回答——\n")
    print(answer)


if __name__ == "__main__":
    main()
