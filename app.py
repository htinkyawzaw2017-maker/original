"""Recap Studio MM: a Burmese-first video recap, voice-over and subtitle app."""

import json
import re
import shutil
import subprocess
import textwrap
import time
import uuid
from pathlib import Path

import edge_tts
import google.generativeai as genai
import requests
import streamlit as st
import whisper
import yt_dlp
from google.cloud import texttospeech
from google.oauth2 import service_account

APP_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = APP_DIR / "user_sessions"
SESSIONS_DIR.mkdir(exist_ok=True)
st.set_page_config(page_title="Recap Studio MM", page_icon="🎞️", layout="wide")

if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex
SESSION_DIR = SESSIONS_DIR / st.session_state.session_id
SESSION_DIR.mkdir(parents=True, exist_ok=True)

PATHS = {
    "source": SESSION_DIR / "source.mp4",
    "audio": SESSION_DIR / "source_audio.wav",
    "voice": SESSION_DIR / "recap_voice.mp3",
    "bgm": SESSION_DIR / "background_music.mp3",
    "caption_source": SESSION_DIR / "caption_source.mp4",
    "caption_audio": SESSION_DIR / "caption_audio.wav",
    "caption_ass": SESSION_DIR / "captions.ass",
    "caption_srt": SESSION_DIR / "captions.srt",
    "caption_video": SESSION_DIR / "captioned_video.mp4",
}

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Noto+Sans+Myanmar:wght@400;500;600;700&display=swap');
      :root { --ink:#e9edf6; --muted:#9ca8bd; --line:rgba(193,207,232,.14); --aqua:#30d5c8; }
      .stApp { background:radial-gradient(circle at 15% -10%,rgba(48,213,200,.17),transparent 28rem),radial-gradient(circle at 92% 5%,rgba(142,125,255,.16),transparent 28rem),#0b1020; color:var(--ink); font-family:"Noto Sans Myanmar","DM Sans",sans-serif; }
      [data-testid="stSidebar"] { background:#101726; border-right:1px solid var(--line); }
      [data-testid="stSidebar"] * { color:var(--ink); }
      .block-container { max-width:1420px; padding-top:2.2rem; padding-bottom:4rem; }
      h1,h2,h3,h4,p,label,.stMarkdown { color:var(--ink) !important; }
      .hero { padding:1.8rem 2rem 1.65rem; margin:0 0 1.5rem; border:1px solid rgba(96,225,216,.26); border-radius:22px; background:linear-gradient(120deg,rgba(22,42,60,.95),rgba(29,31,64,.86)); box-shadow:0 18px 55px rgba(0,0,0,.22); }
      .eyebrow { color:var(--aqua) !important; font-size:.74rem; font-weight:700; letter-spacing:.16em; text-transform:uppercase; margin:0 0 .65rem; }
      .hero h1 { font-family:"DM Sans","Noto Sans Myanmar",sans-serif; font-size:2.25rem; margin:0; }
      .hero p { color:#c4cee0 !important; margin:.55rem 0 0; font-size:1rem; }
      .metric { padding:.85rem 1rem; min-height:5.6rem; border-radius:14px; border:1px solid var(--line); background:rgba(20,28,44,.83); }
      .num { font:700 1.24rem "DM Sans"; color:var(--aqua); }
      .label,.section-lead,.small-note { color:var(--muted) !important; font-size:.84rem; margin-top:.35rem; }
      .section-title { font:700 1.17rem "DM Sans","Noto Sans Myanmar",sans-serif; margin:.2rem 0; }
      .section-lead { margin:0 0 1rem; font-size:.9rem; }
      .stButton > button,.stDownloadButton > button { border:0; border-radius:10px; color:#06161a !important; font-weight:700; background:linear-gradient(100deg,var(--aqua),#7ce6d5); min-height:2.65rem; }
      .stTextInput input,.stTextArea textarea,[data-baseweb="select"] > div,[data-testid="stFileUploader"] { background:#111a2a !important; color:var(--ink) !important; border-color:rgba(193,207,232,.20) !important; border-radius:10px !important; }
      .stTextArea textarea { line-height:1.9; }
      [data-baseweb="tab-list"] { gap:.45rem; border-bottom:1px solid var(--line); }
      button[data-baseweb="tab"] { color:var(--muted); font-weight:700; padding:.75rem 1rem; }
      button[data-baseweb="tab"][aria-selected="true"] { color:var(--aqua); border-bottom-color:var(--aqua); }
      .callout { padding:1rem 1.1rem; margin:.7rem 0 1rem; border-left:3px solid var(--aqua); border-radius:0 10px 10px 0; background:rgba(48,213,200,.075); color:#cdd8e9; }
    </style>
    """,
    unsafe_allow_html=True,
)


def init_state():
    for key, value in {
        "api_keys": [], "google_creds": None, "raw_transcript": "", "final_script": "",
        "script_editor": "", "processed_video": None, "processed_audio": None,
        "caption_video": None, "srt_path": None, "publish_kit": "",
    }.items():
        st.session_state.setdefault(key, value)


init_state()


def load_dictionary():
    path = APP_DIR / "dictionary.txt"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def pronunciation_dictionary():
    path = APP_DIR / "pronunciation.txt"
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            if key.strip() and value.strip():
                result[key.strip()] = value.strip()
    return result


def require_ffmpeg():
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return True
    st.error("FFmpeg မတွေ့ပါ။")
    return False


def run_media(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as error:
        return False, str(error)
    return (True, "") if result.returncode == 0 else (False, (result.stderr or "Media processing failed.")[-900:])


def duration_of(path):
    if not require_ffmpeg():
        return 0
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], capture_output=True, text=True, check=False)
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return 0


def save_upload(upload, destination):
    destination.write_bytes(upload.getbuffer())


def transcribe(video, audio, language=None):
    """Render Free Tier RAM (512MB) သက်သာစေရန် Gemini API ဖြင့် တိုက်ရိုက် transcribe လုပ်ခြင်း"""
    if not require_ffmpeg():
        return None, None
    ok, details = run_media(["ffmpeg", "-y", "-i", str(video), "-vn", "-acodec", "libmp3lame", "-b:a", "64k", str(SESSION_DIR / "audio_small.mp3")])
    if not ok:
        st.error(f"အသံထုတ်မရပါ — {details}")
        return None, None

    if st.session_state.api_keys:
        try:
            genai.configure(api_key=st.session_state.api_keys[0])
            small_audio = SESSION_DIR / "audio_small.mp3"
            audio_file = genai.upload_file(path=str(small_audio))
            while audio_file.state.name == "PROCESSING":
                time.sleep(1)
                audio_file = genai.get_file(audio_file.name)
            
            prompt = "Transcribe the spoken audio into plain text accurately without timestamps or commentary."
            if language:
                prompt += f" The language is {language}."
                
            model = genai.GenerativeModel(st.session_state.model_name)
            response = model.generate_content([audio_file, prompt])
            genai.delete_file(audio_file.name)
            text = response.text.strip() if response.text else ""
            return text, []
        except Exception as api_err:
            st.warning(f"Cloud transcription error, falling back to local: {api_err}")

    # Fallback to tiny whisper if Gemini fails
    try:
        model = whisper.load_model("tiny")
        options = {"task": "transcribe"}
        if language:
            options["language"] = language
        data = model.transcribe(str(SESSION_DIR / "audio_small.mp3"), **options)
        return data.get("text", "").strip(), data.get("segments", [])
    except Exception as error:
        st.error(f"Speech recognition မအောင်မြင်ပါ — {error}")
        return None, None


def download_video(url, destination):
    options = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": str(destination), "merge_output_format": "mp4",
        "quiet": True, "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(options) as client:
            client.download([url])
        return destination.exists(), ""
    except Exception as error:
        return False, str(error)


BURMESE_RULES = """
သင်သည် မြန်မာပရိသတ်အတွက် အတွေ့အကြုံရှိသော recap narrator ဖြစ်သည်။
အောက်က transcript ကို အဓိပ္ပာယ်မပျက်စေဘဲ စကားပြောသဘာဝကျသော မြန်မာ recap narration အဖြစ် ပြန်ရေးပါ။

မဖြစ်မနေလိုက်နာရမည့် စည်းကမ်းများ
1. စဖွင့်ချိတ်ဆက်ချက် → အခြေအနေ/နောက်ခံ → ပြဿနာ → အလှည့်အပြောင်း → ရလဒ် → အဆုံးသတ်အနှစ်ချုပ် အစဉ်လိုက်စီးဆင်းအောင်ရေးပါ။
2. မြင်ကွင်းဖော်ပြချက်၊ shot, scene, camera, timestamp၊ ခေါင်းစဉ်၊ bullet list နှင့် meta စာသားများ လုံးဝမထည့်ပါနှင့်။
3. လူအမည်၊ နေရာအမည်၊ ငွေပမာဏ၊ အစဉ်လိုက်ဖြစ်ရပ်ကို transcript ထဲကအတိုင်း တိတိကျကျထိန်းပါ။ ခန့်မှန်းချက် မရေးပါနှင့်။
4. စံမြန်မာစကားပြောပုံကိုသုံးပါ။ ဝါကျတစ်ကြောင်းလျှင် အဓိပ္ပာယ်တစ်ခုသာပါအောင် ရှင်းလင်းအောင်ရေးပါ။
5. အသံပြောအရှိန်ပြောင်းရန်လိုမှသာ [action], [sad], [happy], [whisper], [normal] tag ကို ဝါကျမတိုင်မီ ထည့်နိုင်သည်။
6. Output တွင် recap narration စာသားသီးသန့်သာ ပြန်ပေးပါ။
""".strip()


def recap_prompt(transcript, tone, language):
    if language == "မြန်မာ":
        return f"{BURMESE_RULES}\n\nNarration tone: {tone}\n\nTranscript:\n{transcript}"
    return f"""
You are a professional recap narrator. Rewrite this transcript as a natural {language} voice-over.
Use this order: hook, context, conflict, turning point, outcome, takeaway.
Preserve facts only. Do not output headings, scene directions, timestamps, bullets, or translation notes.
Return only the finished narration.

Tone: {tone}
Transcript: {transcript}
""".strip()


def visual_prompt(tone, language):
    if language == "မြန်မာ":
        return f"{BURMESE_RULES}\n\nဤဗီဒီယိုကိုသာအခြေခံ၍ {tone} tone ဖြင့် recap narration ရေးပါ။ မြင်/ကြားရသည့် အချက်များသာထည့်ပြီး နားထောင်သူလိုက်လံနားလည်နိုင်မည့် ဇာတ်ကြောင်းပုံစံဖြင့်ရေးပါ။"
    return f"Write a professional {tone} recap narration in {language} from this video. Use only verifiable events. Do not include scene directions, timestamps, headings, bullets, or unsupported details. Return only the finished narration."


def clean_ai_text(text):
    text = text.strip()
    return re.sub(r"^(?:final script|recap narration|narration)\s*[:：]\s*", "", text, flags=re.I).strip()


def generate(prompt):
    if not st.session_state.api_keys:
        return None, "Gemini API key ကို sidebar မှာ ထည့်ပါ။"
    dictionary = load_dictionary()
    if dictionary:
        prompt = f"အသုံးအနှုန်းနှင့်အမည်များအတွက် ဒီ dictionary ကို ဦးစားပေးလိုက်နာပါ။\n{dictionary}\n\n{prompt}"
    errors = []
    for key in st.session_state.api_keys:
        try:
            genai.configure(api_key=key)
            response = genai.GenerativeModel(st.session_state.model_name).generate_content(prompt)
            text = getattr(response, "text", "").strip()
            if text:
                return clean_ai_text(text), None
            errors.append("AI response မှာစာသားမပါရှိပါ။")
        except Exception as error:
            errors.append(str(error))
    return None, errors[-1] if errors else "AI response မရပါ။"


VOICE_MAP = {
    "မြန်မာ": {"ကျား": "my-MM-ThihaNeural", "မ": "my-MM-NilarNeural"},
    "English": {"ကျား": "en-US-ChristopherNeural", "မ": "en-US-AriaNeural"},
}
GOOGLE_VOICE_MAP = {
    "မြန်မာ": {"ကျား": "my-MM-Standard-A", "မ": "my-MM-Standard-A"},
    "English": {"ကျား": "en-US-Neural2-D", "မ": "en-US-Neural2-F"},
}
VOICE_MODES = {
    "Recap — ပြတ်သားမြန်ဆန်": ("+6%", "+0Hz"),
    "Documentary — တည်ငြိမ်": ("-4%", "-2Hz"),
    "Story — ဇာတ်လမ်းဆန်": ("-7%", "-2Hz"),
    "Energy — စိတ်လှုပ်ရှား": ("+12%", "+2Hz"),
}
EMOTIONS = {
    "[normal]": ("+0%", "+0Hz"), "[sad]": ("-14%", "-12Hz"),
    "[happy]": ("+8%", "+9Hz"), "[action]": ("+20%", "+2Hz"),
    "[whisper]": ("-10%", "-16Hz"),
}


def int_value(value):
    return int(value.replace("%", "").replace("Hz", "").replace("+", ""))


def spoken_number(number):
    try:
        if "." in number:
            whole, fraction = number.split(".", 1)
            return f"{spoken_number(whole)} ဒသမ {spoken_number(fraction)}"
        n = int(number.replace(",", ""))
        if n == 0:
            return "သုည"
        digits = ["", "တစ်", "နှစ်", "သုံး", "လေး", "ငါး", "ခြောက်", "ခုနစ်", "ရှစ်", "ကိုး"]
        units = ((10_000_000, "ကုဋေ"), (1_000_000, "သန်း"), (100_000, "သိန်း"), (10_000, "သောင်း"), (1_000, "ထောင်"), (100, "ရာ"), (10, "ဆယ်"))
        result = []
        for unit, label in units:
            if n >= unit:
                upper, n = divmod(n, unit)
                result.append(spoken_number(str(upper)) + label)
        if n:
            result.append(digits[n])
        spoken = "".join(result).replace("ထောင်", "ထောင့်").replace("ရာ", "ရာ့").replace("ဆယ်", "ဆယ့်")
        return spoken[:-1] + "င်" if spoken.endswith("ထောင့်") else spoken.rstrip("့")
    except (ValueError, IndexError):
        return number


def normalize_tts(text, language):
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    text = re.sub(r"[*#]", "", text).replace('"', "").replace("'", "")
    for source, spoken in sorted(pronunciation_dictionary().items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(re.escape(source), spoken, text, flags=re.I)
    if language == "မြန်မာ":
        text = re.sub(r"\b\d+(?:\.\d+)?\b", lambda match: spoken_number(match.group()), text)
    return re.sub(r"\s+", " ", text.replace("၊", ", ").replace("။", ". ")).strip()


def edge_chunk(text, language, gender, rate, pitch, output):
    try:
        result = subprocess.run(["edge-tts", "--voice", VOICE_MAP[language][gender], "--text", text, f"--rate={rate}", f"--pitch={pitch}", "--write-media", str(output)], capture_output=True, text=True, check=False)
        return result.returncode == 0 and output.exists() and output.stat().st_size > 0
    except OSError:
        return False


def google_chunk(text, language, gender, rate, pitch, output):
    credentials = st.session_state.google_creds
    if credentials is None:
        return False
    try:
        client = texttospeech.TextToSpeechClient(credentials=credentials)
        result = client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=text),
            voice=texttospeech.VoiceSelectionParams(language_code="my-MM" if language == "မြန်မာ" else "en-US", name=GOOGLE_VOICE_MAP[language][gender]),
            audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3, speaking_rate=max(.25, min(4, 1 + rate / 100)), pitch=max(-20, min(20, pitch / 10))),
        )
        output.write_bytes(result.audio_content)
        return output.exists() and output.stat().st_size > 0
    except Exception:
        return False


def create_voice(script, language, gender, delivery, speed, engine):
    if not require_ffmpeg():
        return False, "FFmpeg မရှိပါ။"
    base_rate, base_pitch = VOICE_MODES[delivery]
    current_rate = int_value(base_rate) + round((speed - 1) * 100)
    current_pitch = int_value(base_pitch)
    chunks, index = [], 0
    for item in re.split(r"(\[.*?\])", script):
        item = item.strip()
        if not item:
            continue
        tag = item.lower()
        if tag in EMOTIONS:
            rate, pitch = EMOTIONS[tag]
            current_rate = int_value(base_rate) + round((speed - 1) * 100) + int_value(rate)
            current_pitch = int_value(base_pitch) + int_value(pitch)
            continue
        if tag == "[p]":
            pause = SESSION_DIR / f"pause_{index}.mp3"
            ok, _ = run_media(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", ".65", "-q:a", "9", str(pause)])
            if ok:
                chunks.append(pause)
                index += 1
            continue
        if item.startswith("[") and item.endswith("]"):
            continue
        text = normalize_tts(item, language)
        output = SESSION_DIR / f"voice_part_{index}.mp3"
        ok = google_chunk(text, language, gender, current_rate, current_pitch, output) if engine == "Google Cloud TTS" else edge_chunk(text, language, gender, f"{current_rate:+d}%", f"{current_pitch:+d}Hz", output)
        if not ok:
            return False, "အသံတစ်ပိုင်းဖန်တီးမရပါ။ Voice setting သို့မဟုတ် network ကို စစ်ပါ။"
        chunks.append(output)
        index += 1
    if not chunks:
        return False, "အသံဖန်တီးရန် စာသားမရှိပါ။"
    listing = SESSION_DIR / "voice_list.txt"
    listing.write_text("".join(f"file '{chunk}'\n" for chunk in chunks), encoding="utf-8")
    ok, error = run_media(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c:a", "libmp3lame", "-q:a", "2", str(PATHS["voice"])])
    return (True, "") if ok and PATHS["voice"].exists() else (False, error)


def parse_points(raw, source_duration):
    values = []
    for item in raw.split(","):
        try:
            point = float(item.strip())
            if 1 < point < source_duration - 1 and point not in values:
                values.append(point)
        except ValueError:
            pass
    return sorted(values)


def make_freeze_edit(source, points):
    if not points:
        return source, ""
    clips, start = [], 0
    for index, point in enumerate(points):
        clip, image, hold = SESSION_DIR / f"clip_{index}.mp4", SESSION_DIR / f"freeze_{index}.jpg", SESSION_DIR / f"hold_{index}.mp4"
        tasks = [
            ["ffmpeg", "-y", "-ss", str(start), "-to", str(point), "-i", str(source), "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(clip)],
            ["ffmpeg", "-y", "-ss", str(point), "-i", str(source), "-frames:v", "1", "-q:v", "2", str(image)],
            ["ffmpeg", "-y", "-loop", "1", "-i", str(image), "-t", "2", "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(hold)],
        ]
        for task in tasks:
            ok, error = run_media(task)
            if not ok:
                return None, error
        clips.extend([clip, hold])
        start = point
    tail = SESSION_DIR / "tail.mp4"
    ok, error = run_media(["ffmpeg", "-y", "-ss", str(start), "-i", str(source), "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(tail)])
    if not ok:
        return None, error
    clips.append(tail)
    listing = SESSION_DIR / "freeze_list.txt"
    listing.write_text("".join(f"file '{clip}'\n" for clip in clips), encoding="utf-8")
    output = SESSION_DIR / f"freeze_edit_{int(time.time())}.mp4"
    ok, error = run_media(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(output)])
    return (output, "") if ok else (None, error)


def make_video(source, bgm, bgm_volume, speed, points):
    stage, error = make_freeze_edit(source, points)
    if stage is None:
        return None, error
    output = SESSION_DIR / f"recap_{int(time.time())}.mp4"
    video_filter = f"[0:v]setpts={1 / speed:.5f}*PTS,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v]"
    command, maps = ["ffmpeg", "-y", "-i", str(stage), "-i", str(PATHS["voice"])], ["-map", "[v]"]
    if bgm and bgm.exists():
        command.extend(["-stream_loop", "-1", "-i", str(bgm)])
        audio_filter = f";[2:a]volume={bgm_volume:.2f}[bgm];[1:a][bgm]amix=inputs=2:duration=first:normalize=0[a]"
        maps.extend(["-map", "[a]"])
    else:
        audio_filter = ""
        maps.extend(["-map", "1:a"])
    ok, error = run_media(command + ["-filter_complex", video_filter + audio_filter] + maps + ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(output)])
    return (output, "") if ok and output.exists() else (None, error)


def padauk_font():
    folder = APP_DIR / "fonts_cache"
    folder.mkdir(exist_ok=True)
    font = folder / "Padauk-Bold.ttf"
    if font.exists() and font.stat().st_size > 50_000:
        return font
    try:
        response = requests.get("https://github.com/googlefonts/padauk/raw/main/fonts/ttf/Padauk-Bold.ttf", timeout=20)
        response.raise_for_status()
        font.write_bytes(response.content)
        return font
    except requests.RequestException:
        return None


def ass_time(seconds):
    return f"{int(seconds // 3600)}:{int(seconds % 3600 // 60):02d}:{int(seconds % 60):02d}.{int(seconds % 1 * 100):02d}"


def srt_time(seconds):
    return f"{int(seconds // 3600):02d}:{int(seconds % 3600 // 60):02d}:{int(seconds % 60):02d},{int(seconds % 1 * 1000):03d}"


def write_subtitles(segments):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Recap,Padauk-Bold,42,&H00FFFFFF,&H0000FFFF,&H0010181E,&H60000000,1,0,0,0,100,100,0,0,1,3.2,0.8,2,90,90,62,1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    with PATHS["caption_ass"].open("w", encoding="utf-8") as ass, PATHS["caption_srt"].open("w", encoding="utf-8") as srt:
        ass.write(header)
        for number, item in enumerate(segments, 1):
            start, end, text = float(item["start"]), float(item["end"]), item["text"].strip()
            words = text.replace("{", "(").replace("}", ")").replace("\\", "").split()
            display = text if len(words) <= 8 else "\\N".join(textwrap.wrap(" ".join(words), width=32, break_long_words=False))
            ass.write(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Recap,,0,0,0,,{display}\n")
            srt.write(f"{number}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n\n")


def translate_segments(segments):
    output = []
    for item in segments:
        prompt = f"Translate this subtitle into concise, natural Burmese. Preserve names, numbers and factual meaning. Do not turn it into a recap, add information, title, or commentary. Return one subtitle line only.\n\nSubtitle: {item['text'].strip()}"
        translated, error = generate(prompt)
        if not translated:
            return None, error
        output.append({"start": item["start"], "end": item["end"], "text": translated.replace("\n", " ")})
    return output, None


with st.sidebar:
    st.markdown("## 🎞️ Recap Studio MM")
    st.caption("Burmese-first creator workspace")
    st.divider()
    with st.expander("🔐 AI settings", expanded=True):
        raw_keys = st.text_input("Gemini API key", type="password", key="api_key_input", help="Key ကို session အတွင်းသာသိမ်းထားသည်။ Multiple key များကို comma ဖြင့်ခွဲနိုင်သည်။")
        st.session_state.api_keys = [key.strip() for key in raw_keys.split(",") if key.strip()]
        st.session_state.model_name = st.selectbox("Model", ["gemini-2.5-flash", "gemini-2.5-pro"])
        st.caption("AI rewrite၊ direct video recap နှင့် Burmese subtitle translation အတွက်သာလိုသည်။")
    with st.expander("🔊 Google Cloud TTS (optional)"):
        credentials = st.file_uploader("service_account.json", type=["json"], key="credentials")
        if credentials:
            try:
                st.session_state.google_creds = service_account.Credentials.from_service_account_info(json.load(credentials))
                st.success("Google Cloud TTS ချိတ်ဆက်ပြီးပါပြီ။")
            except (ValueError, TypeError, json.JSONDecodeError):
                st.error("service account JSON ဖိုင်မမှန်ပါ။")
    with st.expander("📥 Video link import"):
        link = st.text_input("YouTube / public video URL")
        if st.button("ဗီဒီယိုဒေါင်းလုဒ်", use_container_width=True):
            if not link.strip():
                st.warning("Video URL ထည့်ပါ။")
            else:
                with st.spinner("ဗီဒီယို ရယူနေသည်…"):
                    ok, error = download_video(link.strip(), PATHS["source"])
                st.success("ဗီဒီယိုရပြီ။ Recap Builder မှာ ဆက်လုပ်ပါ။") if ok else st.error(f"ရယူမရပါ — {error}")
    st.divider()
    if st.button("အသစ်ပြန်စ", use_container_width=True):
        saved_id = st.session_state.session_id
        st.session_state.clear()
        st.session_state.session_id = saved_id
        st.rerun()
    st.markdown('<p class="small-note">အသုံးပြုခွင့်ရှိသော ဗီဒီယိုများကိုသာ upload / import လုပ်ပါ။</p>', unsafe_allow_html=True)


st.markdown('<div class="hero"><p class="eyebrow">Burmese video storytelling workflow</p><h1>Recap Studio MM</h1><p>ဗီဒီယိုတစ်ခုကို ရှင်းလင်းတိကျသော မြန်မာ recap narration၊ voice-over နှင့် subtitle အဖြစ် စနစ်တကျထုတ်လုပ်ပါ။</p></div>', unsafe_allow_html=True)
for column, number, label in zip(st.columns(3), ["01", "02", "03"], ["ဗီဒီယိုထည့်ပြီး transcript ယူပါ", "fact-safe recap ကို AI ဖြင့် ပြင်ပါ", "အသံ၊ MP4 နှင့် subtitle ကို export လုပ်ပါ"]):
    with column:
        st.markdown(f'<div class="metric"><div class="num">{number}</div><div class="label">{label}</div></div>', unsafe_allow_html=True)

recap_tab, subtitle_tab, publish_tab = st.tabs(["✦ Recap Builder", "▣ Subtitle Studio", "↗ Publish Kit"])


with recap_tab:
    st.markdown('<p class="section-title">Recap Builder</p><p class="section-lead">အသံမှရေးမည် mode က transcript ကိုအခြေခံ၍ အချက်အလက်မပျက်သော recap ရေးပေးသည်။</p>', unsafe_allow_html=True)
    left, right = st.columns([1.35, 1])
    with left:
        uploaded = st.file_uploader("ဗီဒီယိုဖိုင်ထည့်ပါ", type=["mp4", "mov", "mkv", "webm"], key="recap_source")
        if uploaded:
            save_upload(uploaded, PATHS["source"])
            st.success(f"{uploaded.name} ကို ready လုပ်ပြီးပါပြီ။")
        if PATHS["source"].exists():
            seconds = duration_of(PATHS["source"])
            st.info(f"Source ready · {seconds:.0f} sec" if seconds else "Source ready")
    with right:
        recap_mode = st.radio("Recap ရေးနည်း", ["ဗီဒီယိုကို AI ကြည့်ပြီးရေးမည် (Render RAM လွတ် - အကြံပြု)", "အသံမှရေးမည်"])
        narration_language = st.selectbox("Narration language", ["မြန်မာ", "English"])
        tone = st.selectbox("Narration tone", ["Movie recap — တင်းကျပ်ပြီးစီးဆင်း", "Documentary — ရှင်းလင်းတည်ငြိမ်", "News recap — အချက်အလက်ဦးစားပေး", "High energy — မြန်ပြီးထိရောက်"])
        source_language = st.selectbox("မူရင်းအသံဘာသာ", ["Auto detect", "မြန်မာ", "English", "Japanese", "Chinese", "Thai"])
    with st.expander("မြန်မာ recap narration ကို ဘယ်လိုတိကျအောင်ပြင်ထားလဲ"):
        st.markdown('<div class="callout">AI ကို စဖွင့်ချိတ်ဆက်ချက် → နောက်ခံ → ပြဿနာ → အလှည့်အပြောင်း → ရလဒ် → အနှစ်ချုပ် အစဉ်လိုက်ရေးရန် ညွှန်ကြားထားပါတယ်။ လူအမည်၊ နေရာအမည်၊ ဂဏန်းနှင့်ဖြစ်ရပ်ကို မူရင်း transcript ထဲကအတိုင်းသာ ထိန်းရပြီး scene, camera, timestamp တို့ကို ထည့်မရေးနိုင်အောင် ကန့်သတ်ထားပါတယ်။</div>', unsafe_allow_html=True)
    if st.button("Recap script ဖန်တီးပါ", type="primary", use_container_width=True):
        if not PATHS["source"].exists():
            st.warning("အရင်ဆုံး ဗီဒီယိုဖိုင် upload လုပ်ပါ သို့မဟုတ် sidebar က link import လုပ်ပါ။")
        elif not st.session_state.api_keys:
            st.warning("AI narration ဖန်တီးရန် sidebar မှာ Gemini API key ထည့်ပါ။")
        elif recap_mode.startswith("ဗီဒီယိုကို AI ကြည့်ပြီးရေးမည်"):
            with st.spinner("ဗီဒီယိုကိုစိစစ်ပြီး recap ရေးနေသည်…"):
                try:
                    genai.configure(api_key=st.session_state.api_keys[0])
                    remote = genai.upload_file(path=str(PATHS["source"]))
                    while remote.state.name == "PROCESSING":
                        time.sleep(2)
                        remote = genai.get_file(remote.name)
                    if remote.state.name == "FAILED":
                        raise RuntimeError("Gemini video processing မအောင်မြင်ပါ။")
                    response = genai.GenerativeModel(st.session_state.model_name).generate_content([remote, visual_prompt(tone, narration_language)])
                    script, error = clean_ai_text(response.text), None
                    genai.delete_file(remote.name)
                except Exception as failure:
                    script, error = None, str(failure)
            if script:
                st.session_state.final_script = script
                st.session_state.script_editor = script
                st.success("Recap narration ready ဖြစ်ပါပြီ။")
            else:
                st.error(f"Recap မဖန်တီးနိုင်ပါ — {error}")
        else:
            codes = {"မြန်မာ": "my", "English": "en", "Japanese": "ja", "Chinese": "zh", "Thai": "th"}
            code = None if source_language == "Auto detect" else codes[source_language]
            with st.spinner("အသံကိုနားထောင်ပြီး recap ရေးနေသည်…"):
                transcript, _ = transcribe(PATHS["source"], PATHS["audio"], code)
                script, error = generate(recap_prompt(transcript, tone, narration_language)) if transcript else (None, "Transcript မရပါ။")
            if script:
                st.session_state.raw_transcript = transcript
                st.session_state.final_script = script
                st.session_state.script_editor = script
                st.success("Recap narration ready ဖြစ်ပါပြီ။")
            else:
                st.error(f"Recap မဖန်တီးနိုင်ပါ — {error}")

    if st.session_state.raw_transcript:
        with st.expander("မူရင်း transcript ကိုကြည့်ရန်"):
            st.write(st.session_state.raw_transcript)

    st.markdown("---")
    st.markdown('<p class="section-title">Narration editor & export</p><p class="section-lead">စကားလုံးနှင့်အမည်များကိုစစ်ပြီး export လုပ်ပါ။ [action], [sad], [happy], [whisper] ကိုလိုအပ်မှသာ ထည့်ပါ။</p>', unsafe_allow_html=True)
    script_text = st.text_area("Final recap narration", key="script_editor", height=310, placeholder="Recap script ကို ဒီနေရာမှာ တိုက်ရိုက်ရေးနိုင်ပါတယ်။")
    st.session_state.final_script = script_text
    voice_column, export_column = st.columns([1.1, 1])
    with voice_column:
        voice_engine = st.radio("Voice engine", ["Edge TTS (free)", "Google Cloud TTS"], horizontal=True)
        voice_language = st.selectbox("Voice language", list(VOICE_MAP))
        gender = st.selectbox("Voice", ["ကျား", "မ"], index=1)
        delivery = st.selectbox("Delivery", list(VOICE_MODES))
        voice_speed = st.slider("Narration speed", .75, 1.35, 1.0, .05)
    with export_column:
        export = st.radio("Export", ["🎬 Recap video (MP4)", "🎧 Voice-over only (MP3)"], horizontal=True)
        video_speed = st.slider("Video speed", .75, 1.5, 1.0, .05)
        freeze = st.text_input("Freeze-frame emphasis (seconds, optional)", placeholder="ဥပမာ 30, 65")
        bgm = st.file_uploader("Background music (optional)", type=["mp3", "wav", "m4a"], key="bgm")
        if bgm:
            save_upload(bgm, PATHS["bgm"])
        bgm_volume = st.slider("BGM volume", 0.0, .5, .12, .01)
    if st.button("Voice-over / video ထုတ်ပါ", type="primary", use_container_width=True):
        if not script_text.strip():
            st.warning("Final recap narration မှာ စာသားထည့်ပါ။")
        elif voice_engine == "Google Cloud TTS" and st.session_state.google_creds is None:
            st.warning("Google Cloud TTS ကိုရွေးထားလျှင် sidebar မှာ service_account.json တင်ပါ။")
        elif export.startswith("🎬") and not PATHS["source"].exists():
            st.warning("MP4 ထုတ်ရန် source video လိုအပ်ပါတယ်။")
        else:
            with st.spinner("အသံဖန်တီးနေသည်…"):
                ok, error = create_voice(script_text, voice_language, gender, delivery, voice_speed, "Google Cloud TTS" if voice_engine == "Google Cloud TTS" else "Edge TTS")
            if not ok:
                st.error(f"Voice-over မထုတ်နိုင်ပါ — {error}")
            elif export.startswith("🎧"):
                st.session_state.processed_audio = str(PATHS["voice"])
                st.success("Voice-over MP3 ပြီးပါပြီ။")
            else:
                with st.spinner("ဗီဒီယိုနှင့်အသံကို ပေါင်းစပ်နေသည်…"):
                    points = parse_points(freeze, duration_of(PATHS["source"]))
                    video, error = make_video(PATHS["source"], PATHS["bgm"] if PATHS["bgm"].exists() else None, bgm_volume, video_speed, points)
                if video:
                    st.session_state.processed_audio = str(PATHS["voice"])
                    st.session_state.processed_video = str(video)
                    st.success("Recap video ပြီးပါပြီ။")
                else:
                    st.error(f"Video မထုတ်နိုင်ပါ — {error}")
    if st.session_state.processed_audio and Path(st.session_state.processed_audio).exists():
        audio = Path(st.session_state.processed_audio)
        st.markdown("#### Voice-over output")
        st.audio(str(audio), format="audio/mpeg")
        st.download_button("MP3 ဒေါင်းလုဒ်", audio.read_bytes(), "recap_voiceover.mp3", "audio/mpeg", use_container_width=True)
    if st.session_state.processed_video and Path(st.session_state.processed_video).exists():
        video = Path(st.session_state.processed_video)
        st.markdown("#### Recap video output")
        st.video(str(video))
        st.download_button("MP4 ဒေါင်းလုဒ်", video.read_bytes(), "recap_studio_mm.mp4", "video/mp4", use_container_width=True)


with subtitle_tab:
    st.markdown('<p class="section-title">Subtitle Studio</p><p class="section-lead">ဗီဒီယိုအသံကို subtitle အဖြစ်ထုတ်ပြီး SRT နှင့် burned-in MP4 နှစ်မျိုးလုံး download လုပ်နိုင်သည်။</p>', unsafe_allow_html=True)
    caption_upload = st.file_uploader("Caption လိုချင်သောဗီဒီယို", type=["mp4", "mov", "mkv", "webm"], key="caption_upload")
    subtitle_language = st.selectbox("Subtitle language", ["မူရင်းအသံအတိုင်း", "မြန်မာ (တိကျသောဘာသာပြန်)"])
    subtitle_source = st.selectbox("မူရင်းအသံဘာသာ", ["Auto detect", "မြန်မာ", "English", "Japanese", "Chinese", "Thai"], key="subtitle_source")
    if caption_upload:
        save_upload(caption_upload, PATHS["caption_source"])
        st.success(f"{caption_upload.name} ကို ready လုပ်ပြီးပါပြီ။")
    if st.button("Subtitle ဖန်တီးပါ", type="primary", use_container_width=True):
        if not PATHS["caption_source"].exists():
            st.warning("ဗီဒီယိုဖိုင်ကို အရင်ထည့်ပါ။")
        elif subtitle_language.startswith("မြန်မာ") and not st.session_state.api_keys:
            st.warning("မြန်မာဘာသာပြန် subtitle အတွက် sidebar မှာ Gemini API key ထည့်ပါ။")
        else:
            codes = {"မြန်မာ": "my", "English": "en", "Japanese": "ja", "Chinese": "zh", "Thai": "th"}
            code = None if subtitle_source == "Auto detect" else codes[subtitle_source]
            with st.spinner("အသံကို subtitle အဖြစ်ပြောင်းနေသည်…"):
                _, segments = transcribe(PATHS["caption_source"], PATHS["caption_audio"], code)
                error = None
                if segments and subtitle_language.startswith("မြန်မာ"):
                    segments, error = translate_segments(segments)
                if not segments:
                    st.error(f"Subtitle မထုတ်နိုင်ပါ — {error or 'အသံစာသားမတွေ့ပါ'}")
                else:
                    font = padauk_font()
                    if not font:
                        st.error("မြန်မာ subtitle font ကိုရယူမရပါ။ Network ကိုစစ်ပြီး ပြန်စမ်းပါ။")
                    else:
                        write_subtitles(segments)
                        ok, error = run_media(["ffmpeg", "-y", "-i", str(PATHS["caption_source"]), "-vf", f"ass={PATHS['caption_ass']}:fontsdir={font.parent}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "copy", str(PATHS["caption_video"])])
                        if ok:
                            st.session_state.caption_video = str(PATHS["caption_video"])
                            st.session_state.srt_path = str(PATHS["caption_srt"])
                            st.success("Subtitle MP4 နှင့် SRT ပြီးပါပြီ။")
                        else:
                            st.error(f"Caption video မထုတ်နိုင်ပါ — {error}")
    if st.session_state.caption_video and Path(st.session_state.caption_video).exists():
        caption_video, srt = Path(st.session_state.caption_video), Path(st.session_state.srt_path)
        st.video(str(caption_video))
        first, second = st.columns(2)
        with first:
            st.download_button("Captioned MP4 ဒေါင်းလုဒ်", caption_video.read_bytes(), "recap_captions.mp4", "video/mp4", use_container_width=True)
        with second:
            st.download_button("SRT ဒေါင်းလုဒ်", srt.read_bytes(), "recap_captions.srt", "text/plain", use_container_width=True)


with publish_tab:
    st.markdown('<p class="section-title">Publish Kit</p><p class="section-lead">Recap script ကနေ publish-ready title, description နှင့် hashtags ကို ထုတ်ပါ။</p>', unsafe_allow_html=True)
    if st.button("Title နှင့် caption idea ဖန်တီးပါ", type="primary", use_container_width=True):
        if not st.session_state.final_script.strip():
            st.warning("Recap Builder မှာ script တစ်ခုဖန်တီး သို့မဟုတ် ရေးထားပါ။")
        elif not st.session_state.api_keys:
            st.warning("Sidebar မှာ Gemini API key ထည့်ပါ။")
        else:
            prompt = f"Based only on this Burmese recap narration, create a concise social publishing kit in Burmese. Return exactly these sections: TITLE IDEAS (5 short, factual, non-clickbait titles), DESCRIPTION (one 2–3 sentence description), HASHTAGS (8 relevant hashtags). Do not invent facts.\n\nNarration:\n{st.session_state.final_script}"
            with st.spinner("Publish kit ပြင်ဆင်နေသည်…"):
                kit, error = generate(prompt)
            if kit:
                st.session_state.publish_kit = kit
            else:
                st.error(f"Publish kit မဖန်တီးနိုင်ပါ — {error}")
    if st.session_state.publish_kit:
        st.code(st.session_state.publish_kit, language=None)
