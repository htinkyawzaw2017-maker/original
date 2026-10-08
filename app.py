import streamlit as st
import os
import json
import subprocess
import time
import shutil
from pathlib import Path
import whisper
import google.generativeai as genai
from dotenv import load_dotenv

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
    "gemini-3.5-flash", 
    "gemini-3.5-flash-lite", 
    "gemini-3.6-flash", 
    "gemini-3.7-flash", 
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash"
]

VOICE_MAP = {
    "မြန်မာ": {"ကျား": "my-MM-ThihaNeural", "မ": "my-MM-NilarNeural"},
    "English": {"ကျား": "en-US-ChristopherNeural", "မ": "en-US-AriaNeural"},
}

def load_progress():
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, 'r') as f:
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
    if not require_ffmpeg(): return 0
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], capture_output=True, text=True, check=False)
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except Exception:
        return 0

def transcribe_local(audio_path, language=None):
    try:
        model = whisper.load_model("tiny")
        options = {"task": "transcribe"}
        if language and language != "Auto detect":
            options["language"] = language
        data = model.transcribe(str(audio_path), **options)
        return data.get("text", "").strip()
    except Exception as error:
        return f"Error: {error}"

def generate_with_fallback(prompt, api_keys):
    if not api_keys:
        return None, "API Key မရှိပါ။ Sidebar တွင် ထည့်ပါ။"
    
    for key in api_keys:
        genai.configure(api_key=key.strip())
        for model_name in MODELS_FALLBACK:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                text = getattr(response, "text", "").strip()
                if text:
                    return text, None
            except Exception:
                continue 
    return None, "Key များနှင့် Model များအားလုံး Limit ပြည့်သွားပါပြီ။"

def create_edge_tts(text, language, gender, output_path):
    voice = VOICE_MAP.get(language, VOICE_MAP["မြန်မာ"])[gender]
    try:
        result = subprocess.run(["edge-tts", "--voice", voice, "--text", text, "--write-media", str(output_path)], capture_output=True, text=True, check=False)
        return result.returncode == 0 and Path(output_path).exists()
    except OSError:
        return False

def smart_sync_video(video_in, audio_in, video_out):
    """
    Advanced Smart Sync logic:
    - If audio > video: Slow down video to match audio length exactly.
    - If audio < video: Speed up video up to maximum 1.25x.
    - If audio is still shorter after 1.25x speedup, trim the remaining video tail.
    """
    v_dur = duration_of(video_in)
    a_dur = duration_of(audio_in)
    
    if v_dur == 0 or a_dur == 0:
        return False, "Duration error (Could not read video or audio length)"
        
    ratio = a_dur / v_dur
    
    if ratio >= 1.0:
        # Audio is longer -> Slow down video
        setpts = ratio
    else:
        # Audio is shorter -> Speed up video
        speed_up = 1.0 / ratio
        if speed_up <= 1.25:
            setpts = ratio
        else:
            setpts = 0.8  # Max 1.25x speed (1 / 1.25 = 0.8)
            
    # Apply setpts and strictly trim to audio duration (-t a_dur)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_in),
        "-i", str(audio_in),
        "-filter_complex", f"[0:v]setpts={setpts:.4f}*PTS[v]",
        "-map", "[v]",
        "-map", "1:a",
        "-t", str(a_dur),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        str(video_out)
    ]
    ok, err = run_media(cmd)
    return ok, err

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

st.set_page_config(page_title="Smart Sync AI Dubber", layout="wide")
st.title("🎬 AI Video Dubber & Smart Sync")
st.markdown("ဗီဒီယိုအရှည်များကို အပိုင်းခွဲပြီး၊ AI ဖြင့်ဘာသာပြန်ကာ၊ **Smart Sync (၁.၂၅ ဆ ကန့်သတ်ချက်ပါဝင်)** စနစ်ဖြင့် ရုပ်နဲ့အသံ အတိအကျညှိပေးမည့်စနစ်။")

if 'progress' not in st.session_state:
    st.session_state.progress = load_progress()

with st.sidebar:
    st.header("⚙️ Settings")
    api_keys_input = st.text_input("Gemini API Keys (Comma separated)", type="password")
    api_keys = [k.strip() for k in api_keys_input.split(",") if k.strip()]
    
    target_lang = st.selectbox("Target Dubbing Language", ["မြန်မာ", "English"])
    voice_gender = st.selectbox("Voice Gender", ["ကျား", "မ"])
    chunk_size = st.slider("Chunk Size (Minutes)", 1, 15, 3)
    tone = st.selectbox("Recap Tone", ["Movie recap — တင်းကျပ်ပြီးစီးဆင်း", "Documentary — ရှင်းလင်းတည်ငြိမ်"])
    
    st.divider()
    if st.button("🗑️ Reset Workspace", type="secondary"):
        for d in [UPLOAD_DIR, CHUNKS_DIR, AUDIO_DIR, PROCESSED_DIR, OUTPUT_DIR]:
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True, exist_ok=True)
        if PROGRESS_FILE.exists(): PROGRESS_FILE.unlink()
        st.session_state.progress = {}
        st.rerun()

prog = st.session_state.progress
uploaded_file = st.file_uploader("Upload Video (MP4/MKV)", type=["mp4", "mkv"])

if uploaded_file:
    file_path = UPLOAD_DIR / uploaded_file.name
    if not file_path.exists():
        file_path.write_bytes(uploaded_file.getbuffer())
        st.session_state.progress = {
            "original_file": str(file_path),
            "status": "uploaded",
            "chunks": [],
            "processed": {}
        }
        save_progress(st.session_state.progress)
        st.rerun()

if prog.get("original_file"):
    st.write("---")
    status = prog.get("status")
    
    # STEP 1: CHUNKING
    if status == "uploaded":
        if st.button("Step 1: Split Video into Chunks", type="primary"):
            with st.spinner("Splitting video (Fast Copy)..."):
                chunks = split_video(prog["original_file"], chunk_size)
                if chunks:
                    prog["chunks"] = chunks
                    prog["status"] = "chunked"
                    save_progress(prog)
                    st.success(f"Video split into {len(chunks)} chunks.")
                    st.rerun()
                else:
                    st.error("Splitting failed. Ensure FFmpeg is installed.")

    # STEP 2: PROCESSING (RESUMABLE)
    if status in ["chunked", "processing"]:
        chunks = prog.get("chunks", [])
        processed = prog.get("processed", {})
        total = len(chunks)
        done = len(processed)
        
        st.progress(done / total if total > 0 else 0)
        st.write(f"Processed: **{done} / {total}** chunks")
        
        if st.button("▶ START / RESUME Processing", type="primary"):
            if not api_keys:
                st.error("ကျေးဇူးပြု၍ Sidebar တွင် API Key ထည့်ပါ။")
                st.stop()
                
            prog["status"] = "processing"
            save_progress(prog)
            status_text = st.empty()
            
            for i, chunk_path in enumerate(chunks):
                chunk_name = Path(chunk_path).name
                if chunk_name in processed:
                    continue # Skip completed chunks
                    
                status_text.text(f"Processing {chunk_name} ({i+1}/{total})...")
                
                # Extract Audio & Transcribe
                audio_path = AUDIO_DIR / f"{chunk_name}.wav"
                run_media(["ffmpeg", "-y", "-i", chunk_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", str(audio_path)])
                
                status_text.text(f"Transcribing {chunk_name}...")
                transcript = transcribe_local(audio_path)
                
                # Gemini Recap Translation
                status_text.text(f"Translating & Recapping {chunk_name}...")
                prompt = f"Tone: {tone}\nTranslate this transcript naturally into {target_lang} for a Voice-Over. Output only the translated text.\n\n{transcript}"
                script, err = generate_with_fallback(prompt, api_keys)
                
                if err or not script:
                    st.error(f"AI Limit reached or error on {chunk_name}: {err}. Hit Resume later.")
                    st.stop()
                
                # TTS Generation
                status_text.text(f"Generating Audio for {chunk_name}...")
                tts_path = AUDIO_DIR / f"tts_{chunk_name}.mp3"
                create_edge_tts(script, target_lang, voice_gender, tts_path)
                
                # Smart Sync
                status_text.text(f"Smart Syncing Video and Audio for {chunk_name}...")
                out_path = PROCESSED_DIR / f"sync_{chunk_name}"
                ok, err = smart_sync_video(chunk_path, tts_path, out_path)
                
                if ok:
                    processed[chunk_name] = str(out_path)
                    prog["processed"] = processed
                    save_progress(prog)
                else:
                    st.error(f"Sync error on {chunk_name}: {err}")
                    st.stop()
            
            prog["status"] = "processed_all"
            save_progress(prog)
            st.rerun()

    # STEP 3: MERGING
    if status == "processed_all":
        st.success("🎉 All chunks processed and synced!")
        if st.button("Step 3: Merge Final Video", type="primary"):
            with st.spinner("Merging all chunks..."):
                list_file = WORKSPACE_DIR / "concat_list.txt"
                with open(list_file, "w", encoding="utf-8") as f:
                    for chunk_path in prog["chunks"]:
                        chunk_name = Path(chunk_path).name
                        safe_path = prog["processed"][chunk_name].replace('\\', '/')
                        f.write(f"file '{safe_path}'\n")
                
                final_out = OUTPUT_DIR / "Final_SmartSync_Dubbed.mp4"
                cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(final_out)]
                ok, err = run_media(cmd)
                
                if ok:
                    prog["status"] = "completed"
                    prog["final_output"] = str(final_out)
                    save_progress(prog)
                    st.rerun()
                else:
                    st.error(f"Merge failed: {err}")

    # STEP 4: DOWNLOAD
    if status == "completed":
        st.balloons()
        final_file = Path(prog["final_output"])
        if final_file.exists():
            st.video(str(final_file))
            with open(final_file, "rb") as f:
                st.download_button("💾 Download Final Dubbed Video", f, file_name="Dubbed_Video_SmartSync.mp4", mime="video/mp4", type="primary")
