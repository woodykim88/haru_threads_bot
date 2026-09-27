# Threads @rabbit.haru1130 자동 게시 (토끼 캐릭터 하루)

잠 많고 당근 좋아하는 20대 감성 토끼 "하루"의 일상·공감 글을 하루 5번(09:00, 12:30, 16:00, 20:00, 23:30) Threads에 올리는 가상 인플루언서 실험 채널입니다.

- 뉴스·제품·링크 없음. 시간대별 분위기(src/channel.py MOODS)와 형식(혼잣말·공감·질문·밸런스 게임·감성 한 줄)을 돌려 가며 씁니다.
- AI 표시는 하지 않는 대신, 하루는 끝까지 토끼 캐릭터로만 말합니다. 실제 사람처럼 보이는 표현(20대 여자, 남친, 출근길 등)은 검수에서 막습니다 (src/persona.py).
- 검수에 두 번 떨어지면 준비된 캐릭터 글로 올립니다 (회차를 건너뛰지 않음, 텔레그램에 ⚠️).
- 텔레그램: 같은 봇, `[Threads 하루]`, 명령 `/haru_stop` `/haru_skip` `/haru_resume`
- 정시 실행: `~/Projects/인스타피드 건강뉴스 자동화/scheduler` (Cloudflare 정시 알람). GitHub cron은 예비.

```
python -m pytest -q
python -m src.main --job preview              # 오늘 5개 시간대 글 미리보기 (게시 안 함)
python -m src.main --job preview --slot 23:30 # 한 시간대만
```
