# 무료 서버에서 24시간 돌리기 (오라클 클라우드 Always Free)

평생 무료 서버에 트레이더를 올립니다. PC를 꺼도 매일 자동으로 돌고, 텔레그램 알림과 휴대폰 대시보드를 쓸 수 있습니다.
처음 한 번 40분 정도 걸립니다. 오라클 화면은 영어가 섞여 있고 메뉴 이름이 조금 바뀔 수 있습니다.

---

## 1. 가입 (홈 리전이 제일 중요)
1. https://signup.cloud.oracle.com 에서 가입 (이메일, 휴대폰, 카드 인증).
   - 카드는 본인 확인용입니다. **Always Free 자원만 쓰면 요금이 나오지 않습니다.**
2. **Home Region 을 `South Korea Central (Seoul)` 또는 `South Korea North (Chuncheon)` 으로 선택.**
   - 홈 리전은 **나중에 못 바꿉니다.** 무료 서버는 홈 리전에서만 만들 수 있습니다.
3. 가입 승인까지 몇 분~몇 시간 걸릴 수 있습니다.

## 2. 서버(인스턴스) 만들기
1. 왼쪽 위 메뉴(≡) → **Compute → Instances → Create instance**.
2. **Image:** `Change image` → **Ubuntu** → `Canonical Ubuntu 24.04`.
3. **Shape:** `Change shape` →
   - 추천: **Specialty and previous generation → `VM.Standard.E2.1.Micro`** (AMD, 메모리 1GB, *Always Free-eligible* 표시). 보통 자리가 있습니다.
   - 또는 **Ampere → `VM.Standard.A1.Flex`** 를 1 OCPU / 6GB 로. 더 넉넉하지만 "Out of capacity(자리 없음)" 오류가 자주 납니다.
4. **Networking:** 새 VCN·공용 서브넷 만들기(기본값), **Assign a public IPv4 address = 예**.
5. **SSH keys:** `Generate a key pair for me` → **Save private key** 를 눌러 키 파일(`ssh-key-….key`)을 받아 **잘 보관**하세요. (잃어버리면 서버에 못 들어갑니다)
6. **Create** → 1~2분 뒤 상태가 `RUNNING`, 화면의 **Public IP address** 를 메모.

> "Out of capacity" 가 나오면: Shape 을 E2.1.Micro 로 바꾸거나, 다른 Availability Domain 을 고르거나, 몇 시간 뒤 다시 시도하세요.

## 3. 클라우드 방화벽에서 8501 열기 (대시보드용)
1. 인스턴스 화면 → **Primary VNIC** 의 **Subnet** 링크 클릭.
2. **Security Lists** → `Default Security List for …` 클릭.
3. **Add Ingress Rules**:
   - Source CIDR: `0.0.0.0/0`
   - IP Protocol: `TCP`
   - Destination Port Range: `8501`
4. **Add Ingress Rules** 저장.
   (서버 안쪽 방화벽은 설치 스크립트가 자동으로 엽니다)

## 4. 서버 접속 (윈도우 PowerShell)
1. 시작 메뉴 → **Windows PowerShell** 실행.
2. 받은 키 파일이 `다운로드` 폴더에 있다면 (파일 이름은 본인 것으로):
```powershell
ssh -i "$HOME\Downloads\ssh-key-2026-11-24.key" ubuntu@<Public IP>
```
3. 처음엔 `Are you sure you want to continue connecting` → `yes` 입력.
4. **`UNPROTECTED PRIVATE KEY FILE`** 오류가 나면 아래 두 줄 실행 후 다시 접속:
```powershell
icacls "$HOME\Downloads\ssh-key-2026-11-24.key" /inheritance:r
```
```powershell
icacls "$HOME\Downloads\ssh-key-2026-11-24.key" /grant:r "$($env:USERNAME):(R)"
```
5. `ubuntu@...:~$` 가 보이면 접속 성공. (붙여넣기는 마우스 오른쪽 클릭)

## 5. 설치·키 넣기·확인
여기부터는 Lightsail 과 똑같습니다 → [README_SERVER.md](README_SERVER.md) 의 **4~8번**을 그대로 따라 하세요.
- 4번: 설치 한 줄 (메모리 1GB 서버면 스왑을 자동으로 만들어 5~10분 걸릴 수 있습니다)
- 5번: `nano ~/stock-briefing/.env` 에 PC 의 `.env` 붙여넣기
- 6번: `--check`, `--test` 확인
- 7번: 휴대폰 대시보드 `http://<Public IP>:8501`
- 8번: PC 의 `scripts\자동실행_해제.bat` 실행 (알림 중복 방지)

## 6. 오라클 무료 서버 주의사항
- **놀고 있는 무료 서버 회수 정책:** 오라클은 7일 동안 CPU·네트워크 사용이 아주 낮은 Always Free 인스턴스를 회수(정지)할 수 있습니다. 트레이더는 장중에만 잠깐씩 API 를 부르므로 **해당될 수 있습니다.**
  - 확실히 피하려면: 메뉴 → **Billing → Upgrade and Manage Payment** 에서 **Pay As You Go** 로 업그레이드. 무료 자원만 쓰면 여전히 0원이고 회수 대상에서 빠집니다.
  - 업그레이드했다면 **Billing → Budgets** 에서 예산 알림(예: 1달러)을 만들어 두면 혹시 모를 과금을 바로 알 수 있습니다.
- **공인 IP:** 인스턴스를 정지·삭제하지 않으면 그대로 유지됩니다. 확실히 고정하려면 *Networking → Reserved Public IPs* 에서 예약 IP 를 만들어 연결 (무료 1개).
- **한국투자증권 API 접속 IP 제한**을 걸어 두었다면 KIS Developers 에 서버 IP 를 추가하세요.
- 그만 쓰려면 인스턴스 → **Terminate** (부트 볼륨도 함께 삭제 체크).

## 자주 쓰는 명령 (서버 접속 후)

| 하고 싶은 것 | 명령 |
|---|---|
| 오늘 바로 시작 (평일 15:10 전) | `sudo systemctl start ai-trader.service` |
| 실행 기록 실시간 보기 (끝: Ctrl+C) | `journalctl -u ai-trader -f` |
| 다음 실행 예정 시각 | `systemctl list-timers \| grep ai-trader` |
| 코드 업데이트 | `bash ~/stock-briefing/deploy/update.sh` |
| 대시보드 비밀번호 확인 | `grep DASHBOARD_PASSWORD ~/stock-briefing/.env` |
| 한 달 뒤 분석용 DB 받기 | 브라우저 `http://<Public IP>:8501/download/trader.db` |
