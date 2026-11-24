# 서초 아침 도시정보 자동 수집

서울시 실시간 도시데이터 API에서 **교대역·고속터미널역·양재역**의 공개 집계 정보를 수집·검수하고, GitHub에 JSON·CSV로 저장해 웹에서 확인하는 개인 학습 프로젝트입니다.

- 웹 화면: https://geunjb-git.github.io/geunjb-git/projects/seoul-morning-brief/
- 실행 설정: `.github/workflows/seoul-morning.yml`
- 목표 시각: **매일 한국 시각 오전 07:30**. GitHub Actions의 예약 실행은 지연되거나 누락될 수 있어 정확한 시각을 보장하지 않습니다.
- 공개 저장 항목: 지역 추정 인구 범위·혼잡도, 도로 상태·평균 속도, 기온·습도·강수 유형·초미세먼지, 항목별 기준 시각, 수집 시각, 검수 결과.

## 흐름과 역할

`GitHub 예약 실행 → Python API 호출 → 검수 → JSON·CSV 저장 → 웹 확인`

기존 서울 상권 프로젝트에서 활용한 API 수집·전처리를 예약 실행과 검수·저장으로 확장하는 실습입니다. 초기 코드·설정·웹 화면 작성과 첫 시험 수집에는 AI 도구를 활용했습니다. 개인이 직접 작성한 모든 코드나 장기간 운영한 실무 시스템으로 주장하지 않습니다. 이후 직접 바꾼 규칙과 실제 예약 실행 기간은 실행 이력에 근거해 기록합니다.

## 검수 기준

1. API 성공 코드와 XML 형식 확인.
2. 요청한 지역명·코드와 응답이 일치하는지 확인.
3. 최소·최대 추정 인구가 누락되지 않았고, 음수가 아니며 최소 ≤ 최대인지 확인.
4. 기온·도로 속도 등 숫자 형식을 확인. 누락값을 0으로 바꾸지 않음.
5. 수집 시각과 인구·도로·날씨의 기준 시각을 구분. 2시간 이상 지난 정보 등에 확인 표시.
6. 같은 실행의 지역 코드 중복을 거부. 같은 날짜 재실행은 해당 날짜의 마지막 성공 스냅샷을 대체.
7. 전부 실패하면 마지막 성공 데이터를 보존하고 `status.json`에 실패 상태를 저장. 일부 실패는 부분 수집으로 표시하며 작업은 실패로 종료해 확인 가능하게 함.

## 파일

- `collector.py`: 수집·검수·저장과 실행 요약.
- `config.json`: 대상 지역과 시간 경과 확인 기준.
- `test_collector.py`: 외부 호출 없이 검수·실패 보존·재실행 동작 점검.
- `docs/projects/seoul-morning-brief/data/latest.json`, `latest.csv`: 마지막 성공·부분 성공 결과.
- `data/status.json`: 가장 최근 실행 상태. 이전 결과와 구분해 표시.
- `data/daily/YYYY-MM-DD.json`, `.csv`: 날짜별 마지막 성공 결과.
- `data/archive.json`: 저장된 날짜 목록.

웹 화면은 GitHub 원본 저장소의 최신 파일을 읽습니다. 예약 작업의 `GITHUB_TOKEN` 커밋이 Pages 자동 빌드를 일으키지 않는 경우에도, 기존 화면에서 저장소의 최신 데이터를 읽도록 구성했습니다. GitHub 원본 응답과 웹 반영에는 캐시 지연이 있을 수 있습니다.

## 실행과 인증키

Python 3.11 이상, 외부 패키지 설치 없이 실행합니다.

```bash
python -m unittest discover -s projects/seoul-morning-brief -p 'test_*.py' -v
python projects/seoul-morning-brief/collector.py --mode manual
```

인증키는 로컬 환경변수 또는 GitHub의 **Settings → Secrets and variables → Actions → Repository secrets**에 `SEOUL_API_KEY`로 저장합니다. 소스 코드·설정 파일·출력 파일에는 키를 적지 않습니다. GitHub Actions는 이 비밀값을 환경변수로 전달합니다.

GitHub Actions 화면에서 수동 실행을 성공시킨 뒤 실제 예약 실행 이력을 확인합니다. 공개 저장소의 표준 Linux runner를 사용하며 유료 서비스나 유료 runner를 설정하지 않습니다. 알림은 GitHub 계정의 Actions 알림 설정에서 이메일·웹 수신 여부를 확인해야 합니다. 실제 알림 수신을 확인하기 전에는 알림이 연결되었다고 주장하지 않습니다.

## 해석 범위와 출처

- 인구 혼잡도는 **역 주변 지역 추정 인구**이며, 지하철 객차 혼잡도·통근 시간·배차 지연을 의미하지 않습니다.
- 한 번의 아침 수집은 해당 시점의 스냅샷입니다. 하루 전체의 평균이나 출퇴근 효과로 해석하지 않습니다.
- 인구·도로·날씨 기준 시각이 서로 다를 수 있습니다. 수동 시험 수집은 아침 예약 수집과 구분해 표시합니다.
- 출처: [서울특별시 서울 열린데이터광장 실시간 도시데이터](https://data.seoul.go.kr/dataList/OA-21285/A/1/datasetView.do)
- [GitHub 예약 실행의 지연·비활성화 조건](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [GitHub 공개 저장소 표준 runner 이용 조건](https://docs.github.com/en/actions/concepts/billing-and-usage)
