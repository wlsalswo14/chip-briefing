# 칩 브리핑 수집 소스 맵

목표: 반도체 뉴스를 `설계 / 공정 / 소자 / 패키징`으로 자동 분류하되, 원문 전체 복제는 피하고 `제목, 링크, 출처, 날짜, 짧은 요약, 근거 URL` 중심으로 저장한다.

## 수집 우선순위

1. 공식 API/RSS
   - 가장 안정적이고 약관 리스크가 낮음.
   - `source_url`을 반드시 보존한다.
2. 공개 RSS/사이트맵
   - 전문 매체와 기업 뉴스룸에 적합.
   - 전문 본문 저장 대신 링크와 요약만 저장한다.
3. 검색 API
   - 네이버 뉴스, 네이버 블로그, Google News 검색 RSS, Brave Search API 등.
   - 동일 기사의 중복 제거가 필요하다.
4. 커뮤니티/API
   - Reddit, Hacker News, 공개 커뮤니티 게시글.
   - 루머/미확인 태그를 기본 적용한다.
5. 제한 소스
   - 로그인, 유료, 봇 차단, 동적 렌더링이 강한 곳은 무리하게 긁지 않는다.
   - X는 공식 API 또는 사용자가 제공한 링크/게시글 ID 기반으로 처리한다.

## 한국어 뉴스/포털

| 소스 | 방법 | 용도 | 비고 |
| --- | --- | --- | --- |
| 네이버 뉴스 검색 | Naver Developers Search API | 한국어 뉴스 발견 | `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` 필요 |
| 네이버 블로그 검색 | Naver Developers Search API | 업계 해설/개인 분석 | 신뢰도는 낮게 시작 |
| 네이버 카페 검색 | Naver Developers Search API 또는 검색 결과 링크 | 커뮤니티 관측 | 공식 API 지원 범위 확인 필요 |
| Google News RSS | 검색 RSS | 다국어 뉴스 발견 | 공식 문서는 약하지만 RSS 접근 가능 |
| 다음/카카오 뉴스 | 공개 검색/RSS 가능 여부 확인 | 한국어 보조 소스 | 자동화 전 robots/약관 확인 |

추천 검색어:

- `반도체 HBM`, `HBM4`, `HBM4E`, `CXL 메모리`
- `반도체 패키징`, `CoWoS`, `하이브리드 본딩`, `인터포저`
- `EUV`, `High NA EUV`, `2나노 공정`, `GAA`
- `AI 반도체`, `ASIC`, `NPU`, `가속기`, `EDA`
- `TSMC`, `삼성전자 파운드리`, `SK하이닉스`, `ASML`, `Micron`

## 공식 기업/기관

| 소스 | 방법 | 추천 섹터 |
| --- | --- | --- |
| Samsung Newsroom | 뉴스룸 RSS/HTML/검색 | 소자, 패키징, 공정 |
| SK hynix Newsroom | 뉴스룸/RSS 확인 | 소자, 패키징 |
| TSMC Press Center | 보도자료 페이지/RSS 확인 | 공정, 패키징 |
| ASML News/Products | 보도자료/제품 페이지 | 공정 |
| NVIDIA Newsroom/Developer Blog | 뉴스룸/RSS | 설계, 패키징 |
| AMD Newsroom | 뉴스룸/RSS | 설계 |
| Intel Newsroom | 뉴스룸/RSS | 설계, 공정, 패키징 |
| Micron Newsroom | 뉴스룸/RSS | 소자 |
| Applied Materials | 뉴스룸/RSS | 공정 |
| Lam Research | 뉴스룸/RSS | 공정 |
| Tokyo Electron | 뉴스룸/RSS | 공정 |
| Cadence Blog/News | RSS/블로그 | 설계 |
| Synopsys Blog/News | RSS/블로그 | 설계 |
| Arm Newsroom | RSS/뉴스룸 | 설계 |
| JEDEC | 공지/표준 | 소자, 패키징 |
| SEMI | 뉴스/블로그 | 공정, 패키징 |
| SIA | 뉴스/리포트 | 산업 전체 |
| CHIPS for America/NIST | 공지/뉴스 | 공정, 정책 |

## 전문 매체/RSS 후보

| 소스 | 방법 | 추천 섹터 |
| --- | --- | --- |
| Semiconductor Engineering | RSS | 설계, 공정, 패키징 |
| Semiconductor Today | RSS | 소자, 공정 |
| SemiWiki | RSS | 설계, 공정 |
| EE Times | RSS/검색 | 설계, 산업 |
| The Register | RSS/검색 | 설계, 산업 |
| AnandTech archive/대체 매체 | 검색 | 설계 |
| Tom's Hardware | RSS/검색 | 설계, 소자 |
| TechPowerUp | RSS/검색 | 설계 |
| ServeTheHome | RSS/검색 | 설계, 패키징 |
| IEEE Spectrum | RSS/검색 | 설계, 소자 |
| DIGITIMES | RSS/검색 | 공급망 |
| The Elec | RSS/검색 | 한국 반도체 |
| Business Korea | RSS/검색 | 한국 반도체 |
| Nikkei Asia | RSS/검색 | 공급망 |
| Reuters | 라이선스/검색/API | 시장/기업 |
| Bloomberg | 유료/검색 링크 | 시장/기업 |
| Barron's/WSJ/FT | 유료/검색 링크 | 시장/기업 |
| SemiAnalysis | RSS/뉴스레터 | 설계, 패키징, 시장 |
| Fabricated Knowledge | RSS/뉴스레터 | 산업 분석 |

## 커뮤니티/소셜

| 소스 | 방법 | 처리 기준 |
| --- | --- | --- |
| X | 공식 X API recent search | 원문 링크 보존, `rumor` 기본 |
| Reddit | Reddit API/PRAW | subreddit별 수집, `community` 기본 |
| Hacker News | Algolia HN Search API | 링크/댓글 분위기 수집 |
| SemiWiki forums/comments | RSS/HTML 확인 | 저빈도 보조 |
| 국내 커뮤니티 | robots/약관 확인 후 링크 중심 | 본문 저장 최소화 |
| YouTube | YouTube Data API/RSS | 제목/설명/링크 중심 |

추천 X 검색 쿼리:

- `(HBM OR HBM4 OR HBM4E OR CoWoS OR "advanced packaging") lang:en`
- `(EUV OR "High NA" OR "2nm" OR GAA OR nanosheet) lang:en`
- `(ASIC OR "AI accelerator" OR TPU OR GPU OR NPU) (chip OR semiconductor) lang:en`
- `(삼성전자 OR SK하이닉스 OR TSMC OR ASML) (반도체 OR HBM OR 파운드리) lang:ko`

추천 Reddit/HN 키워드:

- `HBM`, `CoWoS`, `advanced packaging`, `High NA EUV`, `GAA`, `2nm`, `AI accelerator`, `ASIC`, `EDA`

## 데이터 스키마

```json
{
  "id": "stable-id",
  "headline": "제목",
  "body": "짧은 요약. 원문 전체를 복사하지 않는다.",
  "sector": "설계 | 공정 | 소자 | 패키징",
  "category": "news | analysis | rumor | community | filing",
  "trust": "high | medium | low",
  "created_at": "ISO-8601",
  "placement": "top | main | side",
  "source_name": "출처명",
  "source_url": "https://...",
  "source_note": "공식 보도자료 / RSS / 검색결과 / 커뮤니티 게시글",
  "raw_source_type": "api | rss | html | social | manual",
  "matched_keywords": ["HBM", "CoWoS"]
}
```

## 신뢰도 규칙

| trust | 기준 |
| --- | --- |
| high | 기업/기관 공식 발표, 표준기구 문서, 규제기관/공시 |
| medium | 전문 매체 기사, 저명 분석가 글, 복수 출처 확인 |
| low | X/커뮤니티 단독 주장, 익명 제보, 출처 불명 캡처 |

## 섹터 분류 키워드

설계:

- `ASIC`, `GPU`, `NPU`, `TPU`, `RISC-V`, `Arm`, `EDA`, `IP`, `chiplet architecture`, `interconnect`, `NoC`

공정:

- `EUV`, `High NA`, `GAA`, `nanosheet`, `2nm`, `3nm`, `yield`, `lithography`, `etch`, `deposition`, `metrology`

소자:

- `DRAM`, `NAND`, `HBM`, `MRAM`, `ReRAM`, `CXL memory`, `transistor`, `cell`, `leakage`, `retention`

패키징:

- `CoWoS`, `2.5D`, `3D packaging`, `interposer`, `hybrid bonding`, `bump`, `substrate`, `chiplet`, `advanced packaging`

## 구현 메모

- 네이버/X/Reddit은 API 키를 `.env`로 받아야 한다.
- HTML 크롤링은 robots.txt와 약관 확인 후 허용된 페이지만 사용한다.
- 기사 본문 전체 저장은 피하고, 링크와 짧은 자체 요약을 저장한다.
- 같은 원문 URL, 같은 제목, 같은 canonical URL 기준으로 중복 제거한다.
- 공식 발표와 커뮤니티 루머가 같은 주제를 다루면 공식 발표를 상위에 둔다.
