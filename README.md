# Recap Studio MM

မြန်မာဘာသာကို ဦးစားပေးထားသော video recap, voice-over နှင့် subtitle Streamlit app ဖြစ်ပါတယ်။

## Run လုပ်ရန်

1. Terminal မှာ project folder ထဲဝင်ပါ။

       cd recap-studio-mm

2. Python virtual environment တစ်ခုဖန်တီးပြီး dependency များ install လုပ်ပါ။

       python3 -m venv .venv
       source .venv/bin/activate
       pip install -r requirements.txt

3. FFmpeg ကို install လုပ်ထားကြောင်းစစ်ပါ။

       ffmpeg -version

4. App ကို run ပါ။

       streamlit run app.py

## Recap တစ်ခုလုပ်နည်း

1. Sidebar ရှိ AI settings မှာ Gemini API key ထည့်ပါ။
2. Recap Builder မှာ video ဖိုင်တင်ပါ၊ သို့မဟုတ် public video link ကို sidebar ကနေ import လုပ်ပါ။
3. အသံမှရေးမည် ကိုရွေးပြီး မူရင်းအသံဘာသာနှင့် narration tone ကိုရွေးပါ။
4. Recap script ဖန်တီးပါ ကိုနှိပ်ပါ။ AI က မြန်မာ recap narration စနစ်ဖြင့် ပြန်ရေးပေးပါမယ်။
5. Final narration ကို စစ်ပြီးလိုအပ်လျှင် edit လုပ်ပါ။ အရှိန်အဟုန်အတွက် [action], [sad], [happy], [whisper], [p] ကိုသာ အသုံးပြုပါ။
6. Voice၊ delivery၊ speed၊ optional BGM ကိုရွေးပြီး MP3 သို့မဟုတ် MP4 export လုပ်ပါ။

## မြန်မာ narration quality rule

AI prompt ကို အောက်ပါ flow အတိုင်းအမြဲရေးရန်ပြင်ထားပါတယ်။

**စဖွင့်ချိတ်ဆက်ချက် → နောက်ခံ → ပြဿနာ → အလှည့်အပြောင်း → ရလဒ် → အဆုံးသတ်အနှစ်ချုပ်**

လူအမည်၊ နေရာအမည်၊ ဂဏန်းနှင့်အဖြစ်အပျက်အစဉ်ကို transcript ကနေသာယူပြီး၊ scene description၊ camera direction၊ timestamp၊ မလိုအပ်သော ခန့်မှန်းချက် မထည့်ရန် ကန့်သတ်ထားပါတယ်။

## Subtitle

Subtitle Studio မှာ video ဖိုင်တင်ပြီး original subtitle သို့မဟုတ် fact-preserving မြန်မာဘာသာပြန် subtitle ထုတ်နိုင်ပါတယ်။ Result အဖြစ် burned-in MP4 နဲ့ SRT နှစ်မျိုးရပါမယ်။

## လိုအပ်ချက်

- Python 3.10+
- FFmpeg
- Gemini API key (AI recap နှင့် ဘာသာပြန် subtitle အတွက်)
- Internet connection (Gemini, Edge TTS နှင့် font download အတွက်)

Google Cloud TTS သုံးလိုပါက sidebar မှာ service account JSON ဖိုင်တင်ပါ။
