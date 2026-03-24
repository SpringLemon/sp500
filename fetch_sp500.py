#!/usr/bin/env python3
"""
fetch_sp500.py
- 支持两种数据来源：Alpha Vantage (需要 API key) 或 yfinance
- 计算逻辑基于你给的 TradingView 脚本：
  avgVol10 = mean(volume[-11:-1])  # 前2-11条（不包含当前）
  volChangePct = abs((current_volume - avgVol10) / avgVol10 * 100)
- 当 volChangePct > VOL_PCT_THRESHOLD 且 volume > VOLUME_MIN_THRESHOLD 时发送邮件
配置通过环境变量：
- DATA_BACKEND = 'alpha' or 'yfinance'
- ALPHA_VANTAGE_API_KEY
- EMAIL_TO, EMAIL_FROM, SMTP_SERVER, SMTP_PORT, EMAIL_USERNAME, EMAIL_PASSWORD, EMAIL_USE_SSL (true/false)
- INTERVAL, PERIOD (用于yfinance)
"""
import os
import sys
import time
import logging
from typing import Optional
import pandas as pd
import requests
import smtplib
from email.mime.text import MIMEText

# Optional dependency for yfinance
try:
    import yfinance as yf
except Exception:
    yf = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Configurable thresholds and settings (can come from env)
VOL_PCT_THRESHOLD = float(os.getenv("VOL_PCT_THRESHOLD", "500"))   # % 阈值（示例）
VOLUME_MIN_THRESHOLD = float(os.getenv("VOLUME_MIN_THRESHOLD", "2000"))
DATA_BACKEND = os.getenv("DATA_BACKEND", "yfinance")  # 'alpha' or 'yfinance'
ALPHA_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
SYMBOL = os.getenv("SYMBOL", "^GSPC")  # 标普指数符号
INTERVAL = os.getenv("INTERVAL", "5m")  # yfinance interval
PERIOD = os.getenv("PERIOD", "1d")      # yfinance history period

SMTP_SERVER = os.getenv("SMTP_SERVER", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
EMAIL_USERNAME = os.getenv("EMAIL_USERNAME", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", EMAIL_USERNAME)
EMAIL_TO = os.getenv("EMAIL_TO", EMAIL_USERNAME)
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "true").lower() in ("1","true","yes")

def fetch_with_yfinance(symbol: str, interval: str = "5m", period: str = "1d") -> Optional[pd.DataFrame]:
    if yf is None:
        logging.error("yfinance not installed or failed to import.")
        return None
    try:
        df = yf.download(tickers=symbol, period=period, interval=interval, progress=False, threads=False)
        if df.empty:
            logging.warning("yfinance returned empty dataframe")
            return None
        # Ensure columns: Open, Close, Volume
        df = df.reset_index()
        df.rename(columns={
            "Open": "open",
            "Close": "close",
            "Volume": "volume"
        }, inplace=True)
        return df
    except Exception as e:
        logging.exception("yfinance fetch failed: %s", e)
        return None

def fetch_with_alpha(symbol: str, interval: str = "5min", api_key: str = "") -> Optional[pd.DataFrame]:
    if not api_key:
        logging.error("Alpha Vantage API key not provided")
        return None
    # Alpha Vantage symbol for S&P500 can be ^GSPC or "SPY" (ETF) - check API docs
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_INTRADAY",
        "symbol": symbol,
        "interval": interval,
        "apikey": api_key,
        "outputsize": "compact"
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        j = r.json()
        # parse typical Alpha Vantage structure
        key = next((k for k in j.keys() if "Time Series" in k), None)
        if not key:
            logging.error("unexpected alpha response: %s", j)
            return None
        data = j[key]
        rows = []
        for ts, val in data.items():
            rows.append({
                "timestamp": pd.to_datetime(ts),
                "open": float(val["1. open"]),
                "high": float(val["2. high"]),
                "low": float(val["3. low"]),
                "close": float(val["4. close"]),
                "volume": float(val["5. volume"])
            })
        df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
        return df
    except Exception as e:
        logging.exception("Alpha fetch failed: %s", e)
        return None

def compute_volume_metrics(df: pd.DataFrame):
    """
    df: dataframe sorted by time ascending, last row is current bar
    avgVol10: 前2-11条平均成交量 = bars -11 .. -2 (共10条)
    volChangePct: abs((current_volume - avgVol10)/avgVol10*100)
    """
    if df is None or df.shape[0] < 12:
        logging.warning("not enough bars to compute avgVol10 (need at least 12 bars). Have: %s", None if df is None else df.shape[0])
        return None
    current = df.iloc[-1]
    # 前2-11条平均成交量：df[-11:-1]  （注意 pandas iloc slice excludes stop index）
    avg_vol10 = df.iloc[-11:-1]["volume"].mean()
    current_volume = current["volume"]
    vol_change_pct = (abs(current_volume - avg_vol10) / avg_vol10 * 100) if avg_vol10 != 0 else None
    vol_ma = df["volume"].rolling(window=int(os.getenv("MA_PERIOD", "20"))).mean().iloc[-1]
    return {
        "current_volume": float(current_volume),
        "avg_vol10": float(avg_vol10),
        "vol_change_pct": float(vol_change_pct) if vol_change_pct is not None else None,
        "vol_ma": float(vol_ma) if pd.notna(vol_ma) else None,
        "open": float(current.get("open", 0)),
        "close": float(current.get("close", 0)),
    }

def send_email(subject: str, body: str):
    if not SMTP_SERVER or not EMAIL_USERNAME or not EMAIL_PASSWORD:
        logging.error("SMTP config incomplete, cannot send email.")
        return False
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO
    try:
        if EMAIL_USE_SSL:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30)
            server.starttls()
        server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())
        server.quit()
        logging.info("Alert email sent to %s", EMAIL_TO)
        return True
    except Exception:
        logging.exception("sending email failed")
        return False

def main():
    logging.info("Starting sp500 monitor using backend=%s", DATA_BACKEND)
    if DATA_BACKEND == "yfinance":
        df = fetch_with_yfinance(SYMBOL, interval=INTERVAL, period=PERIOD)
    else:
        # alpha variant: interval mapping: yfinance '5m' -> alpha '5min'
        df = fetch_with_alpha(SYMBOL, interval=os.getenv("ALPHA_INTERVAL", "5min"), api_key=ALPHA_KEY)

    if df is None:
        logging.error("no data fetched, exiting")
        sys.exit(1)

    metrics = compute_volume_metrics(df)
    if metrics is None:
        logging.error("metrics not computed, exiting")
        sys.exit(1)

    logging.info("current_volume=%s avgVol10=%s vol_change_pct=%s vol_ma=%s",
                 metrics["current_volume"], metrics["avg_vol10"], metrics["vol_change_pct"], metrics["vol_ma"]) 

    trigger = False
    if metrics["vol_change_pct"] is not None:
        if metrics["vol_change_pct"] > VOL_PCT_THRESHOLD and metrics["current_volume"] > VOLUME_MIN_THRESHOLD:
            trigger = True

    if trigger:
        subject = f"S&P500 Volume Alert: {metrics['vol_change_pct']:.1f}%"
        body = (
            f"Trigger condition met.\n\n"
            f"symbol: {SYMBOL}\n"
            f"current_volume: {metrics['current_volume']}\n"
            f"avgVol10 (prev 2-11 bars): {metrics['avg_vol10']}\n"
            f"vol_change_pct: {metrics['vol_change_pct']:.2f}%\n"
            f"vol_ma: {metrics['vol_ma']}\n"
            f"open: {metrics['open']} close: {metrics['close']}\n"
            f"\nThis alert was generated by GitHub Actions run."
        )
        send_email(subject, body)
    else:
        logging.info("no trigger condition met")

if __name__ == "__main__":
    main()
