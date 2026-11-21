"""매매일지 (SQLite). 대시보드·일일/주간 복기가 모두 여기서 읽는다."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .models import AgentResult, Bar, now_kst
from .settings import DATA_DIR

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts TEXT, date TEXT, kind TEXT, code TEXT, text TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS agent_results (id INTEGER PRIMARY KEY, ts TEXT, date TEXT, signal_id INTEGER, code TEXT,
    no INTEGER, agent TEXT, decision TEXT, reason TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY, ts TEXT, date TEXT, code TEXT, name TEXT, price REAL,
    or_high REAL, or_low REAL, atr REAL, stop REAL, qty INTEGER, status TEXT, reason TEXT, features TEXT);
CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, ts TEXT, date TEXT, signal_id INTEGER, code TEXT, side TEXT,
    qty INTEGER, price REAL, order_no TEXT, status TEXT, filled_qty INTEGER, avg_price REAL, mode TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, date TEXT, code TEXT, name TEXT, signal_id INTEGER,
    entry_ts TEXT, entry_price REAL, qty INTEGER, stop REAL, exit_ts TEXT, exit_price REAL, exit_reason TEXT,
    gross_pnl REAL, cost REAL, net_pnl REAL, mode TEXT);
CREATE TABLE IF NOT EXISTS bars (code TEXT, date TEXT, time TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (code, date, time));
CREATE TABLE IF NOT EXISTS daily_bars (code TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (code, date));
CREATE TABLE IF NOT EXISTS snapshots (key TEXT PRIMARY KEY, ts TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS daily (date TEXT PRIMARY KEY, start_equity REAL, net_pnl REAL, ret_pct REAL,
    trades INTEGER, wins INTEGER, losses INTEGER, mode TEXT);
CREATE TABLE IF NOT EXISTS config_versions (version INTEGER PRIMARY KEY, ts TEXT, yaml TEXT, note TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS proposals (id INTEGER PRIMARY KEY, ts TEXT, changes TEXT, report TEXT, status TEXT);
"""


class Journal:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DATA_DIR / "trader.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.now_fn = now_kst
        with self.lock:
            self.conn.executescript(_SCHEMA)
            self.conn.commit()

    # ── 기본 ──
    def _exec(self, sql: str, args: Iterable[Any] = ()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, tuple(args))
            self.conn.commit()
            return cur.lastrowid

    def query(self, sql: str, args: Iterable[Any] = ()) -> List[Dict[str, Any]]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(args)).fetchall()]

    def _ts(self):
        n = self.now_fn()
        return n.isoformat(timespec="seconds"), n.strftime("%Y%m%d")

    # ── 기록 ──
    def event(self, kind: str, text: str, code: str = "", data: Optional[Dict] = None) -> None:
        ts, d = self._ts()
        self._exec("INSERT INTO events (ts,date,kind,code,text,data) VALUES (?,?,?,?,?,?)",
                   (ts, d, kind, code, text, json.dumps(data or {}, ensure_ascii=False)))
        print(f"[{ts[11:19]}] {kind:<4} {code} {text}")

    def agent_result(self, r: AgentResult, code: str = "", signal_id: Optional[int] = None) -> None:
        ts, d = self._ts()
        self._exec("INSERT INTO agent_results (ts,date,signal_id,code,no,agent,decision,reason,data) "
                   "VALUES (?,?,?,?,?,?,?,?,?)",
                   (ts, d, signal_id, code, r.no, r.agent, r.decision, r.reason,
                    json.dumps(r.data, ensure_ascii=False, default=str)))

    def new_signal(self, sig, features: Dict[str, Any]) -> int:
        ts, d = self._ts()
        return self._exec("INSERT INTO signals (ts,date,code,name,price,or_high,or_low,atr,stop,qty,status,reason,features) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (ts, d, sig.code, sig.name, sig.price, sig.or_high, sig.or_low, sig.atr, sig.stop, sig.qty,
                           "checking", "", json.dumps(features, ensure_ascii=False, default=str)))

    def update_signal(self, sid: int, status: str, reason: str = "", qty: Optional[int] = None) -> None:
        if qty is None:
            self._exec("UPDATE signals SET status=?, reason=? WHERE id=?", (status, reason, sid))
        else:
            self._exec("UPDATE signals SET status=?, reason=?, qty=? WHERE id=?", (status, reason, qty, sid))

    def order(self, signal_id, code, side, qty, price, order_no, status, mode, message="",
              filled_qty=0, avg_price=0.0) -> int:
        ts, d = self._ts()
        return self._exec("INSERT INTO orders (ts,date,signal_id,code,side,qty,price,order_no,status,filled_qty,avg_price,mode,message) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (ts, d, signal_id, code, side, qty, price, order_no, status, filled_qty, avg_price, mode, message))

    def update_order(self, oid: int, status: str, filled_qty: int, avg_price: float) -> None:
        self._exec("UPDATE orders SET status=?, filled_qty=?, avg_price=? WHERE id=?", (status, filled_qty, avg_price, oid))

    def open_trade(self, code, name, signal_id, entry_price, qty, stop, mode) -> int:
        ts, d = self._ts()
        return self._exec("INSERT INTO trades (date,code,name,signal_id,entry_ts,entry_price,qty,stop,mode) "
                          "VALUES (?,?,?,?,?,?,?,?,?)", (d, code, name, signal_id, ts, entry_price, qty, stop, mode))

    def close_trade(self, tid: int, exit_price: float, reason: str, gross: float, cost: float) -> None:
        ts, _ = self._ts()
        self._exec("UPDATE trades SET exit_ts=?, exit_price=?, exit_reason=?, gross_pnl=?, cost=?, net_pnl=? WHERE id=?",
                   (ts, exit_price, reason, gross, cost, gross - cost, tid))

    def open_trades(self) -> List[Dict[str, Any]]:
        return self.query("SELECT * FROM trades WHERE exit_ts IS NULL")

    def snapshot(self, key: str, data: Any) -> None:
        ts, _ = self._ts()
        self._exec("INSERT OR REPLACE INTO snapshots (key,ts,data) VALUES (?,?,?)",
                   (key, ts, json.dumps(data, ensure_ascii=False, default=str)))

    def get_snapshot(self, key: str, default: Any = None) -> Any:
        rows = self.query("SELECT data FROM snapshots WHERE key=?", (key,))
        return json.loads(rows[0]["data"]) if rows else default

    def save_daily(self, date, start_equity, net_pnl, trades, wins, losses, mode) -> None:
        ret = net_pnl / start_equity * 100 if start_equity else 0.0
        self._exec("INSERT OR REPLACE INTO daily (date,start_equity,net_pnl,ret_pct,trades,wins,losses,mode) "
                   "VALUES (?,?,?,?,?,?,?,?)", (date, start_equity, net_pnl, ret, trades, wins, losses, mode))

    # ── 시세 데이터 (백테스트·타임머신용) ──
    def save_bars(self, code: str, bars: List[Bar]) -> None:
        with self.lock:
            self.conn.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?)",
                                  [(code, b.date, b.time, b.open, b.high, b.low, b.close, b.volume) for b in bars if b.date])
            self.conn.commit()

    def save_daily_bars(self, code: str, bars: List[Bar]) -> None:
        with self.lock:
            self.conn.executemany("INSERT OR REPLACE INTO daily_bars VALUES (?,?,?,?,?,?,?)",
                                  [(code, b.date or b.time, b.open, b.high, b.low, b.close, b.volume) for b in bars])
            self.conn.commit()

    def bars(self, code: str, date: str) -> List[Bar]:
        rows = self.query("SELECT * FROM bars WHERE code=? AND date=? ORDER BY time", (code, date))
        return [Bar(time=r["time"], date=r["date"], open=r["open"], high=r["high"], low=r["low"],
                    close=r["close"], volume=r["volume"]) for r in rows]

    def bar_dates(self, code: Optional[str] = None) -> List[str]:
        if code:
            rows = self.query("SELECT DISTINCT date FROM bars WHERE code=? ORDER BY date", (code,))
        else:
            rows = self.query("SELECT DISTINCT date FROM bars ORDER BY date")
        return [r["date"] for r in rows]

    def daily_bars(self, code: str, before: Optional[str] = None, n: int = 30) -> List[Bar]:
        if before:
            rows = self.query("SELECT * FROM daily_bars WHERE code=? AND date<? ORDER BY date DESC LIMIT ?", (code, before, n))
        else:
            rows = self.query("SELECT * FROM daily_bars WHERE code=? ORDER BY date DESC LIMIT ?", (code, n))
        return [Bar(time=r["date"], date=r["date"], open=r["open"], high=r["high"], low=r["low"],
                    close=r["close"], volume=r["volume"]) for r in reversed(rows)]
