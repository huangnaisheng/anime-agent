"""
api_client.py —— API 统一封装：
  - LLM（文本 + 视觉）：DeepSeek Flash（便宜主力）
  - ASR（语音识别）：DashScope Paraformer（DeepSeek 没有 ASR）

两者都是 OpenAI 兼容接口，所以文本/视觉走同一个 OpenAI SDK，
语音识别在 transcribe.py 里用 requests 单独调。
"""
import os
import base64
import yaml
from openai import OpenAI


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_key(section):
    """从某个 provider 配置段读 key：先看 api_key，再看环境变量。"""
    key = section.get("api_key") or os.environ.get(section.get("api_key_env", ""))
    if not key:
        raise RuntimeError(
            f"没找到 API Key：请在环境变量 {section.get('api_key_env')} 里设置，"
            "或在 config.yaml 对应的 api_key 里填。"
        )
    return key


def llm_client(cfg):
    sec = cfg["llm"]
    return OpenAI(api_key=get_key(sec), base_url=sec.get("base_url"))


def _thinking_kwargs(sec):
    """DeepSeek 默认开思考模式（会多吐 reasoning token、更贵）。
    配置里 thinking: false 就关掉它，省钱。"""
    if sec.get("thinking") is False:
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {}


def chat_text(cfg, messages, model=None, temperature=0.2):
    """纯文本对话，返回回答字符串。"""
    sec = cfg["llm"]
    model = model or sec.get("model", "deepseek-flash")
    kw = dict(model=model, messages=messages, temperature=temperature)
    kw.update(_thinking_kwargs(sec))
    resp = llm_client(cfg).chat.completions.create(**kw)
    return resp.choices[0].message.content or ""


def describe_image(cfg, image_path, question, detail=None):
    """用 LLM 的视觉能力看一张本地图片，返回文字描述。"""
    sec = cfg["llm"]
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    ext = os.path.splitext(image_path)[1].lower().lstrip(".")
    mime = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(ext, "image/png")

    img = {"url": f"data:{mime};base64,{b64}"}
    if detail:                       # 可选 detail="low" 再省一点（会把图缩到 512）
        img["detail"] = detail

    kw = dict(
        model=sec.get("model", "deepseek-flash"),
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": img},
                {"type": "text", "text": question},
            ],
        }],
    )
    kw.update(_thinking_kwargs(sec))
    resp = llm_client(cfg).chat.completions.create(**kw)
    return resp.choices[0].message.content or ""
