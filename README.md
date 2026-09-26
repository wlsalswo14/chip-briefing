# 칩 브리핑

반도체 뉴스와 커뮤니티 반응을 매일 수집해 정적 웹 페이지와 날짜별 아카이브로 제공하는 프로젝트입니다.

## 구조

```text
index.html                 메인 뉴스·커뮤니티 화면의 마크업
archive.html               날짜별 아카이브 화면의 마크업
assets/css/site.css        공통 디자인 시스템과 메인 화면 스타일
assets/css/archive.css     아카이브 전용 레이아웃
assets/js/shared.js        날짜·보안·정렬·TOP 10 공통 유틸리티
assets/js/main.js          메인 화면 상태와 상호작용
assets/js/archive.js       아카이브 날짜 탐색과 기사 리더
articles.json              최신 브리핑의 단일 데이터 원본
archive/index.json         날짜별 스냅샷 색인
archive/YYYY-MM-DD.json    날짜별 브리핑 스냅샷
collect_news.py            수집·중복 제거·요약·점수화 파이프라인
```

HTML에는 뉴스 데이터가 중복 삽입되지 않습니다. 메인과 아카이브는 각각 JSON을 불러옵니다. 수집된 기사는 모델 호출 없이 `sources.json`의 키워드 가중치로 설계·공정·소자·패키징·신제품/발표·실적/투자/정책/인사 여섯 탭 중 하나에 배정합니다. 제목 매칭은 가중치의 2배, 스니펫만 매칭된 경우는 1배로 계산하고, 어느 탭에서도 0점인 기사는 버립니다. 같은 점수면 최신 기사가 앞섭니다. 이후 탭별 상위 10개(최대 60개)를 본문 요약해 `summary_article_ids`에 저장하고, 같은 탭의 후보가 10개를 넘으면 남은 후보 일부를 `headline_article_ids`에 제목·원문 링크로 게시합니다(`CHIP_BRIEFING_HEADLINE_LIMIT`, 기본 20개, 0이면 무제한). 후보가 10개 이하인 탭은 제목 전용 뉴스로 채우지 않습니다. 요약은 탭마다 예산을 새로 잡지 않고 하나의 전역 예산을 공유하며, 실패하면 같은 탭의 다음 순위로 넘어갑니다. Daily Summary TOP 10은 상세 기사 중 본문 기반 중요도와 최신순으로 선정하고, 커뮤니티 TOP 10은 `community_top10_ids`를 사용합니다.

## 로컬 실행

```powershell
python -m http.server 4173 --bind 127.0.0.1
```

- 메인: <http://127.0.0.1:4173/>
- 아카이브: <http://127.0.0.1:4173/archive.html>

`file://`로 직접 열면 JSON 요청이 차단될 수 있으므로 로컬 서버를 사용합니다.

## 수집

```powershell
python collect_news.py
```

환경 변수 예시는 `.env.example`을 참고합니다. 실제 키와 Secret은 저장소에 커밋하지 않습니다. 키워드 사전은 `sources.json`의 `sector_keywords`에 탭별 가중치 3·2·1 버킷으로 들어 있고, 수집 쿼리는 `queries.ko`/`queries.en`에 있습니다. 여섯 탭의 상세 목표는 각각 10개이므로 정상적인 최대 상세 기사 수는 60개입니다. 실제 후보가 더 적은 탭은 그 수만큼만 요약합니다. 후보가 충분한데 본문 요약 실패로 목표를 못 채운 실행만 `degraded` 상태로 기록되어 다음 자동 실행에서 재시도됩니다. 수집 파이프라인 점검은 `CHIP_BRIEFING_COLLECT_ONLY=1`(탭별 후보 수와 0점 탈락 수만 출력), 요약 스모크는 `CHIP_BRIEFING_SMOKE_SUMMARIES=2`(상위 2건만 요약)를 사용합니다. Reddit 수집에는 `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`가 필요합니다.

커뮤니티 수집 경로는 다음과 같습니다.

- 네이버 카페: 공식 네이버 카페 검색 API. 응답에 게시시각이 없어 수집시각으로 표시하며, 최근 7일 아카이브 URL과 비교해 반복 노출을 막습니다.
- 디시인사이드: 공개 최신 게시물 검색에서 제목·갤러리·URL·시각만 수집합니다.
- 클리앙: `robots.txt`가 허용하는 공개 게시판(모두의공원·주식한당·AI당)의 글 목록 메타데이터만 수집합니다. 차단된 검색 경로는 호출하지 않습니다.
- 에펨코리아: 일반 봇의 검색 경로가 차단되어 있으므로 네이버 공식 웹검색 API에서 공개 글 링크를 찾습니다.
- Reddit: OAuth Data API로 지정 서브레딧의 최신 글을 검색합니다.

커뮤니티 후보에서는 출처가 제공하는 이미지 플래그와 제목·URL의 사진성 신호를 이용해 사진·스크린샷·밈·갤러리 중심 글을 제외합니다. 남은 글은 게시글에 드러난 주제와 반응을 분리해 요약하고, 설계 주제와 프론티어 반도체 기업에 가중치를 주어 매일 TOP 10만 제공합니다. 단순 링크 공유는 커뮤니티 전체의 반응으로 과장하지 않고 뚜렷한 찬반이 확인되지 않는다고 표시합니다.

### Reddit API 설정

Reddit은 2026년 6월부터 API 접근 전에 명시적 승인을 요구합니다. OAuth 키만 생성해서는 안 됩니다.

1. [비상업적 Data API 신청서](https://support.reddithelp.com/hc/en-us/requests/new?ticket_form_id=14868593862164)를 제출합니다. 역할은 Developer로, Devvit이 맞지 않는 이유는 외부 GitHub Actions가 오프플랫폼 정적 브리핑을 생성하기 때문이라고 설명합니다.
2. 읽기 전용, 대상 서브레딧, 하루 약 5회 검색, 원문 링크 제공, 광고·판매·AI 학습·게시·투표·DM 없음, Gemini를 이용한 한국어 요약 여부와 삭제 대응 계획을 사실대로 기재합니다.
3. Reddit의 명시적 승인 회신을 기다립니다.
4. 승인 후 Reddit 계정으로 <https://www.reddit.com/prefs/apps>에 로그인해 **create another app → script** 앱을 만듭니다. redirect URI가 필수이면 `http://127.0.0.1:8080`을 입력합니다.
5. 앱 이름 아래 문자열을 `REDDIT_CLIENT_ID`, `secret` 옆 문자열을 `REDDIT_CLIENT_SECRET`으로 사용하고, User-Agent는 `script:chip-briefing:v2.0 (by /u/본인레딧아이디)`로 설정합니다.
6. 로컬 `.env`와 GitHub Actions Repository secrets에 인증값 3개를 넣습니다. 승인 후에만 GitHub Actions Repository variable `REDDIT_DATA_API_APPROVED=true`를 추가합니다.

수집기는 `REDDIT_DATA_API_APPROVED=true`가 아니면 Reddit 요청을 실행하지 않습니다. 정책은 [Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)와 [Data API 안내](https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data)를 따릅니다.

## 자동 실행

`.github/workflows/daily_update.yml`이 매일 `06:48 KST`에 GitHub 서버에서 실행됩니다. 같은 워크플로의 중복 실행은 concurrency 그룹으로 직렬화됩니다.

## 기본 검사

```powershell
python -m unittest discover -s tests -v
python -m py_compile collect_news.py send_telegram_archive.py
git diff --check
```

화면 변경은 데스크톱과 모바일에서 메인 탭, Daily Summary TOP 10, 아카이브 날짜 선택, 기사 리더, 콘솔 오류와 가로 넘침을 함께 확인합니다.
