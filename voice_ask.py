"""
voice_ask.py —— 语音提问：按住说话 → 录音 → 自动转文字 → 丢给 ask 回答（不剧透）。

用法：
    python voice_ask.py --episode 5

依赖（录音需要）：
    pip install sounddevice numpy
"""
import os
import sys
import argparse
import tempfile

from api_client import load_config
from transcribe import transcribe_local
from ask import answer_question

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def record_mic(wav_path, sample_rate=16000, channels=1):
    """录音：按回车开始，再按回车结束。返回是否录到了声音。"""
    try:
        import sounddevice as sd
        import numpy as np
        import wave
    except ImportError as e:
        print(f"❌ 缺少录音依赖：{e}")
        print("   请先运行：pip install sounddevice numpy")
        raise SystemExit(1)

    frames = []

    def _cb(indata, frame_count, time_info, status):
        frames.append(indata.copy())

    input("🎤 按回车开始录音……")
    with sd.InputStream(samplerate=sample_rate, channels=channels,
                        dtype="int16", callback=_cb):
        print("   ● 录音中，说完了再按一次回车结束")
        input()

    if not frames:
        return False

    audio = np.concatenate(frames, axis=0)
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)               # int16
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())
    return True


def main():
    ap = argparse.ArgumentParser(description="语音提问（录音 → 识别 → 不剧透回答）")
    ap.add_argument("--episode", type=int, required=True, help="你现在看到第几集")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)

    wav = os.path.join(tempfile.mkdtemp(), "question.wav")
    if not record_mic(wav):
        print("没录到声音，重试一次吧。")
        return

    print("识别中……")
    result = transcribe_local(cfg, wav)
    question = (result["full_text"] or "").strip()
    print(f"你问的是：{question}")

    if not question:
        print("没识别出内容，再说一次？")
        return

    answer = answer_question(cfg, args.episode, question)
    if answer is None:
        print("⚠ 没有档案。请先运行 build_archive.py 生成，再提问。")
        return

    print("\n——回答——\n")
    print(answer)


if __name__ == "__main__":
    main()
