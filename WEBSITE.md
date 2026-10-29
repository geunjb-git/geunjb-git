# 웹 포트폴리오 관리

- 공개 주소: https://geunjb-git.github.io/geunjb-git/
- 게시 위치: main 브랜치의 docs 폴더
- 본문: docs/index.html
- 디자인과 모바일 화면: docs/style.css
- 그래프 전환과 미리보기: docs/app.js
- 발표자료: docs/files
- 이미지: docs/assets

별도 설치나 빌드 없이 동작하는 정적 HTML 웹사이트입니다. GitHub Pages에서 main /docs를 게시 원본으로 사용합니다.

웹페이지 수치를 바꿀 때는 연결한 발표자료·README·분석 노트북의 대상, 기간, 지표 분모도 함께 확인합니다. 고객별 원본 데이터나 인증 파일은 업로드하지 않습니다.

로컬 미리보기:

```bash
python -m http.server 8000 --directory docs
```

브라우저에서 http://localhost:8000 으로 접속합니다.
