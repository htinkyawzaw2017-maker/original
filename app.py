import streamlit as st
import os
import json
import subprocess
import time
import shutil
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Safe import for new Gemini SDK
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

# Safe import for whisper
try:
    import whisper
except ImportError:
    whisper = None

load_dotenv()
GEMINI_PROXY = os.getenv("GEMINI_PROXY", "none").strip()
if GEMINI_PROXY.lower() != "none" and GEMINI_PROXY != "":
    os.environ['HTTP_PROXY'] = GEMINI_PROXY
    os.environ['HTTPS_PROXY'] = GEMINI_PROXY

APP_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = APP_DIR / "workspace"
UPLOAD_DIR = WORKSPACE_DIR / "uploads"
CHUNKS_DIR = WORKSPACE_DIR / "chunks"
AUDIO_DIR = WORKSPACE_DIR / "audio"
PROCESSED_DIR = WORKSPACE_DIR / "processed"
OUTPUT_DIR = WORKSPACE_DIR / "output"
PROGRESS_FILE = WORKSPACE_DIR / "progress.json"

for d in [UPLOAD_DIR, CHUNKS_DIR, AUDIO_DIR, PROCESSED_DIR, OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

MODELS_FALLBACK = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]

VOICE_MAP = {
    "မြန်မာ": {"ကျား": "my-MM-ThihaNeural", "မ": "my-MM-NilarNeural"},
    "English": {"ကျား": "en-US-ChristopherNeural", "မ": "en-US-AriaNeural"},
}

def load_progress():
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_progress(data):
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def require_ffmpeg():
    return shutil.which("ffmpeg") and shutil.which("ffprobe")

def run_media(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        return (True, "") if result.returncode == 0 else (False, result.stderr)
    except OSError as error:
        return False, str(error)

def duration_of(path):
    if not require_ffmpeg() or not Path(path).exists():
        return 0
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=False
    )
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except Exception:
        return 0

def add_log(message, icon="ℹ️"):
    now = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{now}] {icon} {message}"
    if 'activity_logs' not in st.session_state:
        st.session_state.activity_logs = []
    st.session_state.activity_logs.append(log_entry)

def transcribe_audio(audio_path, api_keys, language="auto"):
    """Cloud-first transcription with Gemini (llvmlite/local compilation safe)"""
    if api_keys and genai is not None:
        for key in api_keys:
            try:
                client = genai.Client(api_key=key.strip())
                uploaded_audio = client.files.upload(file=str(audio_path))
                while uploaded_audio.state.name == "PROCESSING":
                    time.sleep(1)
                    uploaded_audio = client.files.get(name=uploaded_audio.name)
                
                prompt = "Transcribe the spoken audio into clean dialogue script accurately without commentary or metadata."
                if language and language != "auto":
                    prompt += f" The spoken language is {language}."
                
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[uploaded_audio, prompt]
                )
                try:
                    client.files.delete(name=uploaded_audio.name)
                except Exception:
                    pass
                if response.text:
                    return response.text.strip(), None
            except Exception:
                continue

    if whisper is not None:
        try:
            model = whisper.load_model("tiny")
            opts = {"task": "transcribe"}
            if language and language != "auto":
                opts["language"] = language
            data = model.transcribe(str(audio_path), **opts)
            return data.get("text", "").strip(), None
        except Exception as e:
            return None, str(e)

    return None, "Transcription failed. Please check Gemini API Key."

def generate_narration(prompt, api_keys):
    if not api_keys:
        return None, "API Key မရှိပါ။ Sidebar တွင် ထည့်သွင်းပါ။"
    
    if genai is None:
        return None, "google-genai library မရှိပါ။ Terminal တွင် 'pip install google-genai' ရိုက်ပါ။"

    for key in api_keys:
        client = genai.Client(api_key=key.strip())
        for model_name in MODELS_FALLBACK:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if response.text:
                    return response.text.strip(), None
            except Exception:
                continue
    return None, "API Key သို့မဟုတ် Quota Limit ပြည့်သွားပါပြီ။ Key အသစ် လဲပေးပါ။"

def create_edge_tts(text, language, gender, raw_output_path):
    """Raw Edge-TTS generation"""
    voice = VOICE_MAP.get(language, VOICE_MAP["မြန်မာ"])[gender]
    try:
        result = subprocess.run(
            ["edge-tts", "--voice", voice, "--text", text, "--write-media", str(raw_output_path)],
            capture_output=True, text=True, check=False
        )
        return result.returncode == 0 and Path(raw_output_path).exists()
    except OSError:
        return False

def smooth_and_pad_audio(raw_audio_path, output_audio_path, pad_start=0.20, pad_end=0.35, fade_len=0.20):
    """
    Smooth Audio Engine:
    - Silence padding: Adds 0.20s ambient silence at start, 0.35s at end to prevent clipping.
    - Audio Cross-fade: Applies smooth fade-in and natural fade-out to eliminate hard cuts.
    """
    dur = duration_of(raw_audio_path)
    if dur <= 0.1:
        shutil.copy(raw_audio_path, output_audio_path)
        return True
    
    pad_start_ms = int(pad_start * 1000)
    total_dur = dur + pad_start + pad_end
    fade_out_start = max(0.0, total_dur - fade_len)
    
    # FFmpeg filter: adelay (start silence) + apad (end silence) + afade in/out
    filter_str = (
        f"[0:a]adelay={pad_start_ms}|{pad_start_ms},"
        f"apad=pad_dur={pad_end:.2f},"
        f"afade=t=in:st=0:d={fade_len:.2f},"
        f"afade=t=out:st={fade_out_start:.2f}:d={fade_len:.2f}[outa]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(raw_audio_path),
        "-filter_complex", filter_str,
        "-map", "[outa]",
        "-c:a", "libmp3lame", "-q:a", "2",
        str(output_audio_path)
    ]
    ok, err = run_media(cmd)
    if not ok:
        shutil.copy(raw_audio_path, output_audio_path)
    return True

def smart_sync_video(video_in, audio_in, video_out, mute_original_bgm=True):
    """
    Smart Sync Algorithm:
    - Mutes original video BGM/SFX completely (maps ONLY input 1:a) if mute_original_bgm is True.
    - Ratio = Audio / Video
    - Audio > Video: Slow down video to match audio length.
    - Audio < Video: Speed up video up to 1.25x max limit; trim remaining tail.
    """
    v_dur = duration_of(video_in)
    a_dur = duration_of(audio_in)
    
    if v_dur == 0 or a_dur == 0:
        return False, "Duration measurement failed."
        
    ratio = a_dur / v_dur
    if ratio >= 1.0:
        setpts = ratio
    else:
        speed_up = 1.0 / ratio
        setpts = ratio if speed_up <= 1.25 else 0.8  # Max 1.25x speed limit

    # Pure MUTE of original video audio: -map 1:a ensures 0:a is completely omitted
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_in),
        "-i", str(audio_in),
        "-filter_complex", f"[0:v]setpts={setpts:.4f}*PTS[v]",
        "-map", "[v]",
        "-map", "1:a",
        "-t", str(a_dur),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        str(video_out)
    ]
    return run_media(cmd)

def split_video(input_path, chunk_mins):
    chunk_secs = chunk_mins * 60
    output_pattern = str(CHUNKS_DIR / "chunk_%04d.mp4")
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-c", "copy", "-f", "segment",
        "-segment_time", str(chunk_secs),
        "-reset_timestamps", "1", output_pattern
    ]
    ok, _ = run_media(cmd)
    if ok:
        return sorted([str(p) for p in CHUNKS_DIR.glob("chunk_*.mp4")])
    return []

# Custom UI Styling
st.set_page_config(page_title="AI Video Dubber & Smart Sync Pro", page_icon="🎬", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&family=Noto+Sans+Myanmar:wght@400;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', 'Noto Sans Myanmar', sans-serif;
    }
    
    /* Main Background */
    .stApp {
        background: radial-gradient(circle at 10% 0%, #151e33 0%, #090d16 100%);
        color: #e2e8f0;
    }
    
    /* Studio Header Banner */
    .header-card {
        background: linear-gradient(135deg, rgba(30, 41, 59, 0.7), rgba(15, 23, 42, 0.9));
        border: 1px solid rgba(56, 189, 248, 0.25);
        border-radius: 16px;
        padding: 24px 28px;
        margin-bottom: 24px;
        box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.5);
    }
    
    .header-title {
        font-size: 2.1rem;
        font-weight: 800;
        background: linear-gradient(90deg, #38bdf8, #818cf8, #c084fc);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0;
    }
    
    .header-desc {
        color: #94a3b8;
        font-size: 0.95rem;
        margin-top: 6px;
        margin-bottom: 0;
    }

    /* Step Pipeline Badges */
    .step-badge {
        display: inline-flex;
        align-items: center;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 0.82rem;
        font-weight: 700;
        margin-right: 8px;
        margin-bottom: 8px;
    }
    .step-active {
        background: rgba(56, 189, 248, 0.15);
        color: #38bdf8;
        border: 1px solid #38bdf8;
    }
    .step-done {
        background: rgba(34, 197, 94, 0.15);
        color: #22c55e;
        border: 1px solid #22c55e;
    }
    .step-pending {
        background: rgba(148, 163, 184, 0.1);
        color: #64748b;
        border: 1px solid rgba(148, 163, 184, 0.2);
    }

    /* Terminal Console Card */
    .terminal-box {
        background: #050811;
        border: 1px solid rgba(56, 189, 248, 0.2);
        border-radius: 12px;
        padding: 16px;
        font-family: 'JetBrains Mono', 'Fira Code', monospace;
        font-size: 0.85rem;
        color: #38bdf8;
        max-height: 220px;
        overflow-y: auto;
        line-height: 1.6;
        box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.7);
    }
</style>
""", unsafe_allow_html=True)

# Session States
if 'progress' not in st.session_state:
    st.session_state.progress = load_progress()
if 'activity_logs' not in st.session_state:
    st.session_state.activity_logs = [f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 AI Dubbing Studio Initialized."]

# Header UI
st.markdown("""
<div class="header-card">
    <div class="header-title">🎬 AI Video Dubber & Smart Sync Pro</div>
    <div class="header-desc">
        Smooth Audio Engine (Silence Padding + Cross-fade) & Full BGM Mute • 1.25x Smart Sync
    </div>
</div>
""", unsafe_allow_html=True)

# Sidebar Settings
with st.sidebar:
    st.markdown("### ⚙️ Studio Settings")
    api_keys_input = st.text_input("Gemini API Keys (Comma separated)", type="password", help="အလိုအလျောက် key လှည့်သုံးပေးမည်")
    api_keys = [k.strip() for k in api_keys_input.split(",") if k.strip()]
    
    st.markdown("#### 🎙️ Voice & Audio")
    target_lang = st.selectbox("Target Dubbing Language", ["မြန်မာ", "English"])
    voice_gender = st.selectbox("Voice Gender", ["ကျား", "မ"], index=1)
    
    st.markdown("#### 🔇 Audio Engineering")
    mute_original = st.toggle("Mute Original BGM/SFX (အသံသီးသန့်)", value=True, help="မူရင်းရုပ်ရှင်ထဲမှ သီချင်းနှင့် ဆူညံသံများကို အပြီးပိတ်ပြီး AI စကားပြောသံကိုသာ သန့်ရှင်းစွာ ထည့်သွင်းမည်။")
    enable_smooth = st.toggle("Smooth Audio Engine (Padding + Fade)", value=True, help="စကားမပြတ်စေရန် ရှေ့နောက် အသံတိတ်ထည့်ပြီး Cross-fade ဖြင့် ချောမွေ့အောင်ညှိမည်။")
    
    with st.expander("🎛️ Audio Smoothing Parameters", expanded=False):
        pad_start = st.slider("Start Delay (Seconds)", 0.05, 0.50, 0.20, 0.05)
        pad_end = st.slider("End Silence (Seconds)", 0.10, 0.80, 0.35, 0.05)
        fade_len = st.slider("Cross-fade Length", 0.05, 0.40, 0.20, 0.05)

    st.markdown("#### ⚡ Pipeline Tuning")
    chunk_size = st.slider("Chunk Size (Minutes)", 1, 10, 3, help="Intel Mac တွင် 3 မိနစ်ထားခြင်းဖြင့် RAM ချွေတာနိုင်သည်")
    tone = st.selectbox("Recap / Dialogue Tone", [
        "Movie scene dubbing — စကားပြောသဘာဝကျပြီး သက်ဝင်လှုပ်ရှား",
        "Movie recap — တင်းကျပ်ပြီးစီးဆင်း",
        "Documentary — ရှင်းလင်းတည်ငြိမ်"
    ])
    
    st.divider()
    if st.button("🗑️ Reset Workspace", use_container_width=True):
        for d in [UPLOAD_DIR, CHUNKS_DIR, AUDIO_DIR, PROCESSED_DIR, OUTPUT_DIR]:
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True, exist_ok=True)
        if PROGRESS_FILE.exists():
            PROGRESS_FILE.unlink()
        st.session_state.progress = {}
        st.session_state.activity_logs = [f"[{datetime.now().strftime('%H:%M:%S')}] 🧹 Workspace cleaned."]
        st.rerun()

prog = st.session_state.progress
status = prog.get("status", "idle")

# Visual Pipeline Indicator
col_steps = st.columns(5)
steps_info = [
    ("1. Upload", status != "idle"),
    ("2. Smart Split", status in ["chunked", "processing", "processed_all", "completed"]),
    ("3. AI Dubbing", status in ["processing", "processed_all", "completed"]),
    ("4. Smart Sync", status in ["processed_all", "completed"]),
    ("5. Final Merge", status == "completed")
]
for col, (label, is_done) in zip(col_steps, steps_info):
    with col:
        badge_class = "step-done" if is_done else "step-pending"
        icon = "✓" if is_done else "○"
        st.markdown(f'<div class="step-badge {badge_class}">{icon} {label}</div>', unsafe_allow_html=True)

st.write("")

# Video Upload Zone
uploaded_file = st.file_uploader("📂 Video ဖိုင်တင်ပါ (MP4, MKV, MOV)", type=["mp4", "mkv", "mov"])
if uploaded_file:
    file_path = UPLOAD_DIR / uploaded_file.name
    if not file_path.exists():
        file_path.write_bytes(uploaded_file.getbuffer())
        add_log(f"New video uploaded: {uploaded_file.name}", "📥")
        st.session_state.progress = {
            "original_file": str(file_path),
            "status": "uploaded",
            "chunks": [],
            "processed": {}
        }
        save_progress(st.session_state.progress)
        st.rerun()

# Processing Engine
if prog.get("original_file"):
    current_status = prog.get("status")
    
    # STEP 1: Smart Chunking
    if current_status == "uploaded":
        total_duration = duration_of(prog["original_file"])
        st.info(f"📹 Source Video Duration: **{total_duration/60:.2f} မိနစ်** ({total_duration:.1f} စက္ကန့်)")
        if st.button("✂️ Step 1: Split Video into Chunks", type="primary", use_container_width=True):
            with st.spinner("Splitting video with keyframe preservation..."):
                add_log(f"Splitting video into {chunk_size}-minute segments...", "✂️")
                chunks = split_video(prog["original_file"], chunk_size)
                if chunks:
                    prog["chunks"] = chunks
                    prog["status"] = "chunked"
                    save_progress(prog)
                    add_log(f"Created {len(chunks)} chunks successfully.", "✅")
                    st.rerun()
                else:
                    st.error("Splitting failed. FFmpeg ထည့်သွင်းထားခြင်း ရှိမရှိ စစ်ဆေးပါ။")

    # STEP 2 & 3: Processing Chunks with Smooth Audio & Smart Sync
    if current_status in ["chunked", "processing"]:
        chunks = prog.get("chunks", [])
        processed = prog.get("processed", {})
        total = len(chunks)
        done = len(processed)
        
        progress_val = done / total if total > 0 else 0
        st.progress(progress_val)
        st.markdown(f"**Chunk Processing Progress:** `{done} / {total} chunks completed` ({int(progress_val*100)}%)")
        
        col_act1, col_act2 = st.columns([1.5, 1])
        with col_act1:
            run_btn = st.button("▶ START / RESUME Processing", type="primary", use_container_width=True)
            
        if run_btn:
            if not api_keys:
                st.error("⚠️ Sidebar တွင် Gemini API Key ထည့်သွင်းပေးပါ။")
                st.stop()
                
            prog["status"] = "processing"
            save_progress(prog)
            
            for i, chunk_path in enumerate(chunks):
                chunk_name = Path(chunk_path).name
                if chunk_name in processed:
                    continue
                    
                add_log(f"Starting pipeline on {chunk_name} ({i+1}/{total})...", "⚡")
                
                # 1. Extract audio
                raw_extracted_audio = AUDIO_DIR / f"raw_{chunk_name}.mp3"
                run_media(["ffmpeg", "-y", "-i", chunk_path, "-vn", "-acodec", "libmp3lame", "-b:a", "64k", str(raw_extracted_audio)])
                
                # 2. Transcription
                add_log(f"Transcribing {chunk_name} audio with Cloud AI...", "🎙️")
                transcript, err = transcribe_audio(raw_extracted_audio, api_keys)
                if err or not transcript:
                    add_log(f"Transcription error on {chunk_name}: {err}", "❌")
                    st.error(f"Transcription error: {err}")
                    st.stop()
                
                # 3. AI Translation / Dubbing script
                add_log(f"Generating dialogue dubbing script ({target_lang})...", "✍️")
                prompt = (
                    f"You are a professional movie dubbing director.\n"
                    f"Tone: {tone}\n"
                    f"Translate and adapt the following dialogue transcript into concise, natural, emotionally expressive spoken {target_lang}. "
                    f"Do NOT include brackets, scene descriptions, timestamps, or character tags. "
                    f"Return ONLY the spoken sentences:\n\n{transcript}"
                )
                script, err = generate_narration(prompt, api_keys)
                if err or not script:
                    add_log(f"Script error on {chunk_name}: {err}", "❌")
                    st.error(f"Script generation error: {err}")
                    st.stop()
                
                # 4. Edge-TTS Generation
                add_log(f"Synthesizing Neural Speech for {chunk_name}...", "🔊")
                raw_tts_path = AUDIO_DIR / f"tts_raw_{chunk_name}.mp3"
                ok = create_edge_tts(script, target_lang, voice_gender, raw_tts_path)
                if not ok:
                    add_log(f"TTS synthesis failed for {chunk_name}.", "❌")
                    st.error("TTS generation failed.")
                    st.stop()
                
                # 5. Smooth Audio Engine (Padding + Fade)
                final_tts_audio = AUDIO_DIR / f"tts_smooth_{chunk_name}.mp3"
                if enable_smooth:
                    add_log(f"Applying Smooth Audio Engine (Padding + Cross-fade)...", "🎛️")
                    smooth_and_pad_audio(raw_tts_path, final_tts_audio, pad_start, pad_end, fade_len)
                else:
                    shutil.copy(raw_tts_path, final_tts_audio)
                
                # 6. Smart Sync with Audio Mute
                add_log(f"Executing Smart Sync (Max 1.25x Speed Limit) & Muting original BGM...", "📐")
                out_synced_video = PROCESSED_DIR / f"synced_{chunk_name}"
                ok, err = smart_sync_video(chunk_path, final_tts_audio, out_synced_video, mute_original_bgm=mute_original)
                
                if ok:
                    processed[chunk_name] = str(out_synced_video)
                    prog["processed"] = processed
                    save_progress(prog)
                    add_log(f"Chunk {chunk_name} synced and saved successfully.", "✅")
                else:
                    add_log(f"Sync error on {chunk_name}: {err}", "❌")
                    st.error(f"Sync error: {err}")
                    st.stop()
            
            prog["status"] = "processed_all"
            save_progress(prog)
            add_log("All video chunks processed and synchronized.", "🎉")
            st.rerun()

    # STEP 4: Concatenation
    if current_status == "processed_all":
        st.success("🎉 All chunks successfully processed with Smooth Audio & Smart Sync!")
        if st.button("🔗 Step 3: Merge Final Video", type="primary", use_container_width=True):
            with st.spinner("Concatenating synchronized chunks..."):
                add_log("Merging chunks into final Master MP4...", "🔗")
                list_file = WORKSPACE_DIR / "concat_list.txt"
                with open(list_file, "w", encoding="utf-8") as f:
                    for chunk_path in prog["chunks"]:
                        chunk_name = Path(chunk_path).name
                        safe_path = prog["processed"][chunk_name].replace('\\', '/')
                        f.write(f"file '{safe_path}'\n")
                
                final_out = OUTPUT_DIR / "Final_Dubbed_SmartSync.mp4"
                cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(final_out)]
                ok, err = run_media(cmd)
                
                if ok:
                    prog["status"] = "completed"
                    prog["final_output"] = str(final_out)
                    save_progress(prog)
                    add_log(f"Master Video ready: {final_out.name}", "🏆")
                    st.rerun()
                else:
                    st.error(f"Merge error: {err}")

    # STEP 5: Final Result & Download
    if current_status == "completed":
        st.balloons()
        final_file = Path(prog["final_output"])
        if final_file.exists():
            st.markdown("### 🏆 Final Output Preview")
            st.video(str(final_file))
            with open(final_file, "rb") as f:
                st.download_button(
                    "💾 Download Final Master Dubbed Video (MP4)",
                    f,
                    file_name="Dubbed_SmartSync_Master.mp4",
                    mime="video/mp4",
                    type="primary",
                    use_container_width=True
                )

# Live Activity Terminal Console
st.write("")
st.markdown("### 📟 Live Activity Console")
logs_html = "<br>".join(reversed(st.session_state.activity_logs[-15:]))
st.markdown(f'<div class="terminal-box">{logs_html}</div>', unsafe_allow_html=True)
