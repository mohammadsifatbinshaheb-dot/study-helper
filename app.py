import asyncio
import json
import os
import tempfile

import edge_tts
import fitz  # PyMuPDF
import google.generativeai as genai
import streamlit as st

# ---------------- সেটিংস ----------------
MODEL_NAME = "gemini-3.8-flash" # AI Studio তে যে ফ্রি মডেল চলে সেই নাম দাও
VOICES = {
    "বাংলা": ("bn-BD-NabanitaNeural", "bn-BD-PradeepNeural"),
    "English": ("en-US-AriaNeural", "en-US-GuyNeural"),
}

st.set_page_config(page_title="Student Study Helper", page_icon="📚", layout="wide")
st.title("📚 Student Study Helper")
st.caption("PDF বা লেখা দাও → সামারি, রুটিন, কুইজ, অডিও, পডকাস্ট ও ভিডিও পাবে")

# ---------------- API Key ----------------
api_key = None
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    pass
if not api_key:
    api_key = st.sidebar.text_input("Gemini API Key", type="password")
    st.sidebar.markdown("[ফ্রি key নাও](https://aistudio.google.com)")

lang = st.sidebar.selectbox("ভাষা", list(VOICES.keys()))
days = st.sidebar.number_input("পরীক্ষার আগে কত দিন আছে?", 1, 60, 7)
make_video = st.sidebar.checkbox("ভিডিও বানাও (ধীর, ছোট লেখায় ভালো)", value=False)


# ---------------- সাহায্যকারী ফাংশন ----------------
def read_input(file, pasted):
    if file is not None:
        doc = fitz.open(stream=file.read(), filetype="pdf")
        return "".join(p.get_text() for p in doc)
    return pasted


def ask_ai(text):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        MODEL_NAME, generation_config={"response_mime_type": "application/json"}
    )
    prompt = f"""তুমি একজন দক্ষ শিক্ষক। নিচের পড়ার বিষয়বস্তু {lang} ভাষায় খুব সহজ করে বোঝাও।
শুধু JSON দাও, এই কাঠামোতে:
{{
 "summary": "ছোট সামারি",
 "key_points": ["গুরুত্বপূর্ণ পয়েন্ট", "..."],
 "routine": [{{"day": 1, "task": "কী পড়বে"}}],
 "quiz": [{{"q": "প্রশ্ন", "options": ["A","B","C","D"], "answer": "সঠিক অপশনের লেখা", "why": "কেন"}}],
 "flashcards": [{{"front": "প্রশ্ন/টার্ম", "back": "উত্তর"}}],
 "podcast": [{{"speaker": "A", "text": "কথা"}}, {{"speaker": "B", "text": "কথা"}}],
 "slides": [{{"title": "শিরোনাম", "bullets": ["পয়েন্ট"], "narration": "এই স্লাইডে যা বলা হবে"}}]
}}
নিয়ম: routine এ ঠিক {days} দিনের প্ল্যান দাও। quiz এ ৫টা প্রশ্ন। flashcards ৮টা।
podcast এ ২ জনের (A ও B) আলাপ, ১০-১৪ লাইন, যেন বন্ধুরা আলোচনা করছে।
slides এ ৫-৬টা স্লাইড, প্রতিটায় সর্বোচ্চ ৩টা ছোট bullet।
শুধু নিচের বিষয়বস্তু থেকে বানাও, বাইরে থেকে বানিয়ে লিখো না।

বিষয়বস্তু:
{text[:15000]}"""
    return json.loads(model.generate_content(prompt).text)


async def _tts(text, voice, path):
    await edge_tts.Communicate(text, voice).save(path)


def tts(text, voice, path):
    asyncio.run(_tts(text, voice, path))


def make_podcast(lines, tmpdir):
    v_a, v_b = VOICES[lang]
    out = os.path.join(tmpdir, "podcast.mp3")
    with open(out, "wb") as f:
        for i, line in enumerate(lines):
            p = os.path.join(tmpdir, f"p{i}.mp3")
            tts(line["text"], v_a if line["speaker"] == "A" else v_b, p)
            with open(p, "rb") as part:
                f.write(part.read())
    return out


def find_font(size):
    from PIL import ImageFont

    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansBengali-Regular.ttf",
        "/usr/share/fonts/truetype/lohit-bengali/Lohit-Bengali.ttf",
        "C:/Windows/Fonts/nirmala.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def make_video_file(slides, tmpdir):
    from moviepy.editor import AudioFileClip, ImageClip, concatenate_videoclips
    from PIL import Image, ImageDraw

    voice = VOICES[lang][0]
    clips = []
    for i, s in enumerate(slides):
        img = Image.new("RGB", (1280, 720), (20, 30, 60))
        d = ImageDraw.Draw(img)
        d.text((60, 50), s["title"], font=find_font(56), fill=(255, 215, 0))
        y = 190
        for b in s["bullets"]:
            d.text((80, y), "• " + b, font=find_font(38), fill=(255, 255, 255))
            y += 90
        ip = os.path.join(tmpdir, f"s{i}.png")
        ap = os.path.join(tmpdir, f"s{i}.mp3")
        img.save(ip)
        tts(s["narration"], voice, ap)
        a = AudioFileClip(ap)
        clips.append(ImageClip(ip).set_duration(a.duration + 0.5).set_audio(a))
    out = os.path.join(tmpdir, "lesson.mp4")
    concatenate_videoclips(clips).write_videofile(out, fps=12, logger=None)
    return out


# ---------------- ইনপুট ----------------
file = st.file_uploader("PDF আপলোড করো", type="pdf")
pasted = st.text_area("অথবা এখানে লেখা পেস্ট করো", height=150)

if st.button("🚀 শুরু করো", type="primary"):
    if not api_key:
        st.error("আগে বাম পাশে API Key দাও।")
        st.stop()
    text = read_input(file, pasted)
    if not text or len(text.strip()) < 50:
        st.error("PDF বা লেখা দাও (অন্তত কয়েক লাইন)।")
        st.stop()
    with st.spinner("AI পড়ছে ও সাজাচ্ছে..."):
        try:
            st.session_state["data"] = ask_ai(text)
        except Exception as e:
            st.error(f"সমস্যা হয়েছে: {e}")
            st.stop()
    st.session_state.pop("media", None)

data = st.session_state.get("data")
if data:
    t1, t2, t3, t4, t5, t6 = st.tabs(
        ["📝 সামারি", "📅 রুটিন", "❓ কুইজ", "🃏 ফ্ল্যাশকার্ড", "🎧 অডিও/পডকাস্ট", "🎬 ভিডিও"]
    )
    with t1:
        st.write(data["summary"])
        st.subheader("গুরুত্বপূর্ণ পয়েন্ট")
        for p in data["key_points"]:
            st.markdown(f"- {p}")
    with t2:
        for r in data["routine"]:
            st.markdown(f"**দিন {r['day']}:** {r['task']}")
    with t3:
        for i, q in enumerate(data["quiz"]):
            st.markdown(f"**{i+1}. {q['q']}**")
            choice = st.radio("উত্তর", q["options"], key=f"q{i}", index=None, label_visibility="collapsed")
            if choice:
                if choice == q["answer"]:
                    st.success("✅ সঠিক! " + q["why"])
                else:
                    st.error(f"❌ ভুল। সঠিক উত্তর: {q['answer']}। {q['why']}")
    with t4:
        for c in data["flashcards"]:
            with st.expander(c["front"]):
                st.write(c["back"])
    with t5:
        st.write("নিচের বাটনে চাপ দিলে পডকাস্ট অডিও তৈরি হবে।")
        if st.button("🎙️ পডকাস্ট বানাও"):
            with st.spinner("অডিও বানানো হচ্ছে..."):
                tmp = tempfile.mkdtemp()
                path = make_podcast(data["podcast"], tmp)
                st.session_state["podcast"] = open(path, "rb").read()
        if "podcast" in st.session_state:
            st.audio(st.session_state["podcast"], format="audio/mp3")
            st.download_button("ডাউনলোড", st.session_state["podcast"], "podcast.mp3")
    with t6:
        if not make_video:
            st.info("ভিডিও চাইলে বাম পাশে 'ভিডিও বানাও' টিক দাও।")
        elif st.button("🎬 ভিডিও বানাও"):
            with st.spinner("ভিডিও বানাতে কয়েক মিনিট লাগতে পারে..."):
                tmp = tempfile.mkdtemp()
                path = make_video_file(data["slides"], tmp)
                st.session_state["video"] = open(path, "rb").read()
        if "video" in st.session_state:
            st.video(st.session_state["video"])
            st.download_button("ডাউনলোড", st.session_state["video"], "lesson.mp4")
