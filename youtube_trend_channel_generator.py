#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import requests
import pandas as pd
import openai
import smtplib
from email.message import EmailMessage

# ──────────────────────────────────────────────────────────────────────────────
# 1) 환경변수 읽기
YT_API_KEY     = os.environ.get("YT_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
EMAIL_USER     = os.environ.get("EMAIL_USER")
EMAIL_PASS     = os.environ.get("EMAIL_PASS")
EMAIL_TO       = os.environ.get("EMAIL_TO", EMAIL_USER)

for var, name in [
    (YT_API_KEY,     "YT_API_KEY"),
    (OPENAI_API_KEY, "OPENAI_API_KEY"),
    (EMAIL_USER,     "EMAIL_USER"),
    (EMAIL_PASS,     "EMAIL_PASS"),
]:
    if not var:
        raise RuntimeError(f"환경변수 {name} 가 설정되지 않았습니다.")

openai.api_key = OPENAI_API_KEY

# ──────────────────────────────────────────────────────────────────────────────
# 2) YouTube Data API로 Trending 비디오 50개 가져오기
TREND_URL = "https://www.googleapis.com/youtube/v3/videos"
params = {
    "part":       "snippet,statistics",
    "chart":      "mostPopular",
    "regionCode": "US",      # 필요시 KR 등으로 변경
    "maxResults": 50,
    "key":        YT_API_KEY
}
resp = requests.get(TREND_URL, params=params)
resp.raise_for_status()
items = resp.json().get("items", [])
if not items:
    raise RuntimeError("YouTube Data API에서 인기 비디오 데이터를 가져오지 못했습니다.")

# ──────────────────────────────────────────────────────────────────────────────
# 3) 카테고리 ID → 이름 매핑 (실패 시 Unknown 처리)
cat_ids = list({vi["snippet"]["categoryId"] for vi in items})
cat_map = {}
try:
    cat_url    = "https://www.googleapis.com/youtube/v3/videoCategories"
    cat_params = {
        "part":       "snippet",
        "id":         ",".join(cat_ids),
        "regionCode": "US",
        "key":        YT_API_KEY
    }
    cat_resp = requests.get(cat_url, params=cat_params)
    cat_resp.raise_for_status()
    for c in cat_resp.json().get("items", []):
        cid = c["id"]
        cat_map[cid] = c["snippet"]["title"]
except Exception as e:
    print(f"⚠️ 카테고리 매핑 오류: {e} → 'Unknown' 처리됩니다.")

# ──────────────────────────────────────────────────────────────────────────────
# 4) DataFrame 구성
rows = []
for vi in items:
    cid = vi["snippet"]["categoryId"]
    rows.append({
        "VideoID":     vi["id"],
        "Title":       vi["snippet"]["title"],
        "Category":    cat_map.get(cid, "Unknown"),
        "ViewCount":   int(vi["statistics"].get("viewCount", 0)),
        "LikeCount":   int(vi["statistics"].get("likeCount", 0)),
        "PublishedAt": vi["snippet"]["publishedAt"]
    })
df = pd.DataFrame(rows)

# ──────────────────────────────────────────────────────────────────────────────
# 5) 트렌드 분석: 카테고리별 영상 수 & 평균 조회수
cat_stats = (
    df.groupby("Category")["ViewCount"]
      .agg(VideoCount="count", AvgViews="mean")
      .reset_index()
)
top_cats = (
    cat_stats.sort_values(["AvgViews","VideoCount"], ascending=False)
             .head(5)["Category"]
             .tolist()
)

# ──────────────────────────────────────────────────────────────────────────────
# 6) OpenAI 호출: 채널 아이디어 생성 (new v1 API 인터페이스)
chat_resp = openai.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role":"user","content":
        f"현재 인기 YouTube 트렌드 상위 카테고리: {', '.join(top_cats)}.\n"
        "이 트렌드를 반영해 5가지 새로운 YouTube 채널 아이디어를 "
        "채널명/설명/첫 3개 콘텐츠 주제 형식으로 한국어+영어 병렬로 제안해주세요."
    }],
    temperature=0.7,
    max_tokens=800
)
ideas_text = chat_resp.choices[0].message.content

# ──────────────────────────────────────────────────────────────────────────────
# 7) Excel 리포트 작성
EXCEL_FILE = "yt_trend_channel_ideas.xlsx"
with pd.ExcelWriter(EXCEL_FILE) as writer:
    df.to_excel(writer, sheet_name="RawVideos", index=False)
    cat_stats.to_excel(writer, sheet_name="CategoryStats", index=False)
    pd.DataFrame({"ChannelIdeas": [ideas_text]}).to_excel(
        writer, sheet_name="ChannelIdeas", index=False
    )

# ──────────────────────────────────────────────────────────────────────────────
# 8) 이메일 발송
msg = EmailMessage()
msg["Subject"] = "📈 YouTube 트렌드 분석 & AI 채널 아이디어 리포트"
msg["From"]    = EMAIL_USER
msg["To"]      = EMAIL_TO
msg.set_content("자동 생성된 YouTube 트렌드 분석 및 채널 아이디어 리포트입니다.")

with open(EXCEL_FILE, "rb") as f:
    data = f.read()
msg.add_attachment(data, maintype="application",
                   subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                   filename=EXCEL_FILE)

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
    smtp.login(EMAIL_USER, EMAIL_PASS)
    smtp.send_message(msg)

print("✅ 이메일 발송 완료!")
