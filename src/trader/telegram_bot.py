"""텔레그램: 알림, 매수 승인 버튼, 명령어 (/status /stop /flat /weekly /apply /hold /help).

requests 로 롱폴링한다 (별도 라이브러리 없음). 승인은 등록된 chat_id 에서 온 것만 받는다.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

import requests


@dataclass
class Pending:
    sid: int
    created: float
    message_id: Optional[int]
    status: str = "pending"   # pending | approved | rejected | expired


class Telegram:
    def __init__(self, token: str, chat_id: str):
        self.api = f"https://api.telegram.org/bot{token}"
        self.chat_id = str(chat_id)
        self.pending: Dict[int, Pending] = {}
        self.commands: Dict[str, Callable[[str], Optional[str]]] = {}
        self._offset = 0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    @property
    def enabled(self) -> bool:
        return True

    def _post(self, method: str, **payload) -> Dict:
        try:
            r = requests.post(f"{self.api}/{method}", json=payload, timeout=35)
            body = r.json()
        except Exception as e:  # noqa: BLE001
            print(f"[telegram] {method} 실패 (인터넷 연결 또는 api.telegram.org 차단): {e}")
            return {}
        if not body.get("ok", False):
            print(f"[telegram] {method} 거부: {body.get('error_code')} {body.get('description')} → {explain(body)}")
        return body

    def send(self, text: str) -> Optional[int]:
        res = self._post("sendMessage", chat_id=self.chat_id, text=text[:4000])
        return (res.get("result") or {}).get("message_id")

    def request_approval(self, sid: int, text: str) -> None:
        kb = {"inline_keyboard": [[{"text": "매수", "callback_data": f"ok:{sid}"},
                                   {"text": "거절", "callback_data": f"no:{sid}"}]]}
        res = self._post("sendMessage", chat_id=self.chat_id, text=text[:4000], reply_markup=kb)
        mid = (res.get("result") or {}).get("message_id")
        with self._lock:
            self.pending[sid] = Pending(sid, time.monotonic(), mid)

    def approval_status(self, sid: int, timeout_sec: float) -> str:
        with self._lock:
            p = self.pending.get(sid)
            if not p:
                return "expired"
            if p.status == "pending" and time.monotonic() - p.created > timeout_sec:
                p.status = "expired"
                self._edit_done(p, "⏱ 시간 초과로 취소됨")
            return p.status

    def _edit_done(self, p: Pending, note: str) -> None:
        if p.message_id:
            self._post("editMessageReplyMarkup", chat_id=self.chat_id, message_id=p.message_id,
                       reply_markup={"inline_keyboard": []})
            self._post("sendMessage", chat_id=self.chat_id, text=note, reply_to_message_id=p.message_id)

    def on(self, command: str, fn: Callable[[str], Optional[str]]) -> None:
        self.commands[command.lstrip("/")] = fn

    def handle_update(self, u: Dict) -> None:
        if "callback_query" in u:
            cq = u["callback_query"]
            chat = str(((cq.get("message") or {}).get("chat") or {}).get("id", ""))
            self._post("answerCallbackQuery", callback_query_id=cq.get("id"))
            if chat != self.chat_id:
                return
            kind, _, sid = str(cq.get("data", "")).partition(":")
            with self._lock:
                p = self.pending.get(int(sid)) if sid.isdigit() else None
                if p and p.status == "pending":
                    p.status = "approved" if kind == "ok" else "rejected"
                    self._edit_done(p, "✅ 승인됨 → 주문 진행" if kind == "ok" else "❌ 거절됨")
            return
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id", "")) != self.chat_id:
            return
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            return
        cmd, _, arg = text[1:].partition(" ")
        fn = self.commands.get(cmd.split("@")[0])
        reply = fn(arg.strip()) if fn else "명령: /status /stop /flat /weekly /apply <번호> /hold <번호> /help"
        if reply:
            self.send(reply)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                r = requests.get(f"{self.api}/getUpdates", params={"offset": self._offset, "timeout": 25}, timeout=35)
                for u in r.json().get("result", []):
                    self._offset = u["update_id"] + 1
                    try:
                        self.handle_update(u)
                    except Exception as e:  # noqa: BLE001
                        print(f"[telegram] 처리 실패: {e}")
            except Exception as e:  # noqa: BLE001
                print(f"[telegram] 폴링 실패: {e}")
                time.sleep(3)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()


def explain(body: Dict) -> str:
    """텔레그램 오류를 쉬운 말로."""
    code, desc = body.get("error_code"), str(body.get("description", "")).lower()
    if code == 401:
        return "봇 토큰이 틀렸습니다. BotFather 대화방에서 토큰을 다시 복사해 .env 의 TELEGRAM_BOT_TOKEN 에 넣으세요."
    if code == 404:
        return "봇 토큰 형식이 틀렸습니다 (숫자:영문 형태여야 함, 앞뒤 공백·따옴표 제거)."
    if "chat not found" in desc:
        return "chat_id 가 틀렸거나, 내 봇에게 아직 '시작(Start)'을 누르지 않았습니다."
    if "bot was blocked" in desc:
        return "봇을 차단한 상태입니다. 봇 대화방에서 차단 해제 후 '시작'을 누르세요."
    if "bots can't send messages to bots" in desc:
        return "chat_id 에 봇 자신의 번호를 넣었습니다. @userinfobot 이 알려준 '내' 번호를 넣으세요."
    return "위 메시지를 캡처해 보내주세요."


def diagnose(token: str, chat_id: str) -> int:
    """python -m src.trader.telegram_bot --test : 토큰·chat_id 확인 후 테스트 메시지 전송."""
    if not token or not chat_id:
        print("❌ .env 에 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 비어 있습니다.")
        return 1
    api = f"https://api.telegram.org/bot{token}"
    try:
        me = requests.get(f"{api}/getMe", timeout=15).json()
    except Exception as e:  # noqa: BLE001
        print(f"❌ api.telegram.org 에 연결하지 못했습니다 (인터넷·회사/학교 방화벽·백신 확인): {e}")
        return 1
    if not me.get("ok"):
        print(f"❌ 토큰 확인 실패: {me.get('description')} → {explain(me)}")
        return 1
    print(f"✅ 토큰 OK: 봇 이름 @{me['result'].get('username')}")
    print(f"   .env 의 chat_id: {chat_id}")
    try:
        ups = requests.get(f"{api}/getUpdates", timeout=15).json().get("result", [])
        seen = {}
        for u in ups:
            chat = ((u.get("message") or {}).get("chat") or {})
            if chat.get("id"):
                seen[str(chat["id"])] = chat.get("first_name") or chat.get("title") or ""
        if seen:
            print("   최근 이 봇에게 말을 건 대화방: " + ", ".join(f"{k} ({v})" for k, v in seen.items()))
            if chat_id not in seen:
                print("   ⚠️ .env 의 chat_id 가 위 목록에 없습니다. 위 숫자로 바꿔 보세요.")
    except Exception:  # noqa: BLE001
        pass
    res = requests.post(f"{api}/sendMessage", json={"chat_id": chat_id, "text": "✅ AI 트레이더 연결 테스트 메시지입니다."},
                        timeout=15).json()
    if res.get("ok"):
        print("✅ 테스트 메시지를 보냈습니다. 텔레그램을 확인하세요.")
        return 0
    print(f"❌ 메시지 전송 실패: {res.get('description')} → {explain(res)}")
    return 1


class AutoApprove:
    """모의투자용: 매수 승인을 즉시 자동으로 처리하고, 텔레그램에는 알림만 보낸다.
    (사람 승인 지연 없이 전략 자체의 성능을 재기 위해)"""

    def __init__(self, inner):
        self.inner = inner
        self.enabled = getattr(inner, "enabled", False)

    def send(self, text):
        return self.inner.send(text)

    def request_approval(self, sid, text):
        self.inner.send("🤖 [모의투자 자동 승인]\n" + text.replace("[매수 승인 요청]", "").split("3분 안에")[0].strip())

    def approval_status(self, sid, timeout_sec):
        return "approved"

    def on(self, command, fn):
        self.inner.on(command, fn)

    def start(self):
        self.inner.start()

    def stop(self):
        self.inner.stop()


class NullTelegram:
    """텔레그램 미설정 (드라이런 전용): 승인은 자동, 알림은 콘솔."""
    enabled = False

    def __init__(self):
        self.commands = {}

    def send(self, text: str):
        print("[알림]", text.replace("\n", " | "))

    def request_approval(self, sid: int, text: str) -> None:
        print("[승인 자동]", text.replace("\n", " | "))

    def approval_status(self, sid: int, timeout_sec: float) -> str:
        return "approved"

    def on(self, command, fn):
        self.commands[command.lstrip("/")] = fn

    def start(self):
        pass

    def stop(self):
        pass


if __name__ == "__main__":
    import sys

    from .settings import Secrets
    if "--test" in sys.argv:
        sec = Secrets()
        sys.exit(diagnose(sec.telegram_token, sec.telegram_chat_id))
    print("사용법: python -m src.trader.telegram_bot --test")
