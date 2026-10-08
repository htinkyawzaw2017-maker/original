# Render deployment guide

## 1. Project ကို GitHub သို့တင်ပါ

Project folder အတွင်း Terminal ဖွင့်ပါ။

    cd recap-studio-mm
    git init
    git add .
    git commit -m "Deploy Recap Studio MM to Render"
    git branch -M main

GitHub မှာ private repository အသစ်တစ်ခုဖန်တီးပြီး repository URL ကိုကူးပါ။ ထို့နောက် အောက်ပါ command နှစ်ကြောင်းကို run ပါ။

    git remote add origin YOUR_GITHUB_REPOSITORY_URL
    git push -u origin main

.gitignore က API key, Python environment, user video နှင့် generated output များကို GitHub သို့မတင်အောင် ကာကွယ်ထားပါတယ်။

## 2. Render မှာ Blueprint ဖြင့် deploy လုပ်ပါ

1. Render Dashboard သို့ဝင်ပြီး GitHub account ကို connect လုပ်ပါ။
2. New ကိုနှိပ်ပြီး Blueprint ကိုရွေးပါ။
3. အခုတင်ထားသော GitHub repository ကိုရွေးပါ။
4. Render က repository root ရှိ render.yaml ကိုတွေ့ပြီး Recap Studio MM service ကိုပြပေးပါမယ်။
5. Apply သို့မဟုတ် Create Blueprint ကိုနှိပ်ပါ။

render.yaml က Docker runtime, Singapore region, 1 CPU / 2 GB RAM plan နှင့် auto deploy ကို ကြိုတင်သတ်မှတ်ထားပါတယ်။ Whisper နှင့် video processing ကြောင့် Free 512 MB plan မသုံးရန်အကြံပြုပါတယ်။

## 3. First deploy ကိုစောင့်ပါ

Build လုပ်စဉ်မှာ Python, FFmpeg, Whisper နှင့် PyTorch packages များ install လုပ်ရသဖြင့် ပထမအကြိမ်အချိန်ယူနိုင်ပါတယ်။

Deploy အောင်မြင်လျှင် Render က onrender.com URL တစ်ခုပေးပါမယ်။ URL ကိုဖွင့်ပြီး Recap Studio MM page ပေါ်လာရင် deployment အောင်မြင်ပါပြီ။

## 4. API key လုံခြုံရေး

ဒီ app ကို public အသုံးပြုရန်ရေးထားတာမို့ Gemini API key ကို Render environment variable သို့မဟုတ် GitHub code ထဲမှာ မသိမ်းပါနှင့်။ User တစ်ယောက်ချင်းစီက sidebar ထဲမှာ ကိုယ့် Gemini key ကို တိုက်ရိုက်ထည့်သုံးရပါမယ်။

Google Cloud TTS service account JSON ကိုလည်း GitHub မတင်ပါနှင့်။ လိုအပ်မှသာ private usage အတွက် app sidebar မှာတင်ပါ။

## 5. Deploy ပြီး စမ်းသပ်ရန်

1. Recap Builder မှာ 30 စက္ကန့်မှ 1 မိနစ်ခန့် video စမ်းတင်ပါ။
2. Gemini API key ထည့်ပါ။
3. အသံမှရေးမည် ကိုရွေးပြီး Recap script ဖန်တီးပါ ကိုနှိပ်ပါ။
4. Script ကို စစ်ပြီး Edge TTS voice-over MP3 ကိုအရင်ထုတ်စမ်းပါ။
5. အောင်မြင်လျှင် MP4 export နှင့် Subtitle Studio ကို ဆက်စမ်းပါ။

## 6. Custom domain

Render service ရဲ့ Settings သို့မဟုတ် Custom Domains မှာ သင့် domain ကိုထည့်ပါ။ Render က DNS record ထည့်ရန် value ကိုပြပေးပါမယ်။ Domain provider မှာ record ထည့်ပြီး verify လုပ်ပါ။

## ပြဿနာဖြေရှင်းရန်

- Build error: Deploys tab ရှိ log ကိုဖွင့်ကြည့်ပါ။ requirements.txt နှင့် Dockerfile ကိုပြင်ပြီး GitHub main branch သို့ push လုပ်ပါ။
- Memory error သို့မဟုတ် Whisper လုပ်ရင်း restart ဖြစ်ခြင်း: Render compute ကို 2 GB သို့မဟုတ် ပိုမြင့်သော plan သို့တိုးပါ။
- Upload အလွန်ကြီးခြင်း: app setting က 500 MB အထိသတ်မှတ်ထားပါတယ်။ ဒီထက်ကြီးသော video ကိုစက်ထဲတွင်အရင် compress လုပ်ပါ။
- MP4 နှင့် audio outputs မသိမ်းထားခြင်း: Render server storage က temporary ဖြစ်နိုင်သောကြောင့် download ပြီးပြီးချင်းယူထားပါ။ Long-term file storage လိုလျှင် Cloudflare R2 သို့မဟုတ် Amazon S3 ထည့်သွင်းရန်လိုပါတယ်။
- Push အသစ်လုပ်တိုင်း Render က automatic deploy လုပ်ပေးပါမယ်။
