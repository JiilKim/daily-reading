📚 일일 읽을거리 (Daily Reading)

이 프로젝트는 지정된 과학 뉴스 웹사이트에서 최신 기사를 스크래핑하고, Gemini AI를 이용해 한글로 번역 및 요약하여 GitHub Pages 웹사이트로 제공합니다.

🚀 설정 방법

이 프로젝트가 자동으로 작동하게 하려면 Gemini API 키 설정이 반드시 필요합니다.

1. Gemini API 키 발급받기

Google AI Studio (구글 계정 로그인 필요)로 이동합니다.

새 API 키를 생성합니다.

생성된 API 키(긴 문자열)를 복사해 둡니다.

2. GitHub Repository에 API 키 등록하기

API 키가 코드에 노출되면 안 되므로, GitHub의 "Secrets" 기능을 사용해야 합니다.

이 GitHub Repository의 [Settings] 탭으로 이동합니다.

왼쪽 메뉴에서 [Secrets and variables] > **[Actions]**를 선택합니다.

[New repository secret] 버튼을 클릭합니다.

Name 부분에 GEMINI_API_KEY 라고 정확하게 입력합니다. (대소문자 중요)

Secret 부분에 위에서 복사한 Gemini API 키를 붙여넣습니다.

[Add secret] 버튼을 눌러 저장합니다.

이제 GitHub Actions가 실행될 때마다 이 API 키를 안전하게 사용할 수 있습니다.

3. GitHub Pages 활성화하기

Repository의 [Settings] 탭으로 이동합니다.

왼쪽 메뉴에서 **[Pages]**를 선택합니다.

"Build and deployment" 항목에서 Source를 **[Deploy from a branch]**로 선택합니다.

Branch를 main (혹은 master) 브랜치와 /(root) 폴더로 설정하고 **[Save]**를 누릅니다.

몇 분 기다리면 https://{사용자이름}.github.io/{Repository이름}/ 주소에서 웹사이트를 확인할 수 있습니다.
