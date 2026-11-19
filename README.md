# Institutional Order Flow & Lead-Lag Trading Engine

A Python-based algorithmic trading intelligence system designed for **Nifty 50** and **Bank Nifty** with multi-broker support (**Angel One SmartAPI** for 100% free live feeds, and **DhanHQ**).

---

## Features

1. **Intraday VWAP & Deviation Bands (`vwap_tracker.py`):**
   - Automatically tracks intraday VWAP ($\sum P \times V / \sum V$).
   - Calculates $\pm 1\sigma$ and $\pm 2\sigma$ standard deviation bands.
   - Automatically resets every morning at market open.

2. **Open Interest (OI) Analyzer (`oi_analyzer.py`):**
   - Classifies institutional positioning:
     - **Long Build-Up:** Price $\uparrow$ + OI $\uparrow$ (Bullish)
     - **Short Build-Up:** Price $\downarrow$ + OI $\uparrow$ (Bearish)
     - **Short Covering:** Price $\uparrow$ + OI $\downarrow$ (Bullish short squeeze)
     - **Long Unwinding:** Price $\downarrow$ + OI $\downarrow$ (Bearish exit)
   - Computes **Call Wall** (Resistance) and **Put Wall** (Support) from the live Option Chain.
   - Calculates **Max Pain** and **Put-Call Ratio (PCR)**.

3. **Whale & Iceberg Absorption Detector (`iceberg_detector.py`):**
   - Flags sudden massive volume bursts (e.g., 50k+ contracts).
   - Monitors price action for 15–20 seconds:
     - **ABSORBED:** Huge volume traded with little to no price movement $\rightarrow$ signals hidden iceberg limit absorption and potential reversal.
     - **BREAKOUT:** Aggressive price follow-through in the direction of the whale volume.
     - **REJECTED:** Price strongly reversed against the whale order.

4. **BankNifty $\rightarrow$ Nifty Lead-Lag Monitor (`lead_lag_monitor.py`):**
   - Tracks relative momentum and spread between BankNifty and Nifty.
   - Flags early trading signals when BankNifty surges above/below VWAP ahead of Nifty.

5. **Instant Alerts (`telegram_notifier.py`):**
   - Dispatches formatted alerts to a Telegram Bot/Channel, or displays them directly in the console.

---

## Execution Modes

### 1. Live Free Feed via Angel One SmartAPI (Active & Ready)
Uses Angel One's free live API with automated TOTP login:
```powershell
.\venv\Scripts\python.exe main.py --broker angel
```

### 2. High-Fidelity Simulation Mode
Test offline or on weekends with realistic whale volume spikes and absorption events:
```powershell
.\venv\Scripts\python.exe main.py --simulate
```
