#!/usr/bin/env python3
"""
Stock Market Pro - Yahoo Finance data fetcher
Fast, local-first market research toolkit
"""

import yfinance as yf
import argparse
import json
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.dates import DateFormatter
import pandas as pd
import numpy as np
import os
import sys

def get_price(ticker):
    """Get current price and basic info"""
    stock = yf.Ticker(ticker)
    info = stock.info
    
    current_price = info.get('currentPrice', 'N/A')
    previous_close = info.get('previousClose', 'N/A')
    change = current_price - previous_close if current_price != 'N/A' and previous_close != 'N/A' else 'N/A'
    change_pct = (change / previous_close * 100) if change != 'N/A' and previous_close != 'N/A' else 'N/A'
    
    print(f"{ticker} - Current: ${current_price:.2f}")
    print(f"Previous Close: ${previous_close:.2f}")
    if change != 'N/A':
        print(f"Change: ${change:.2f} ({change_pct:.2f}%)")
    print(f"Volume: {info.get('volume', 'N/A'):,}")
    print(f"Market Cap: ${info.get('marketCap', 0):,}")

def get_fundamentals(ticker):
    """Get fundamental data"""
    stock = yf.Ticker(ticker)
    info = stock.info
    
    print(f"\n{ticker} Fundamentals:")
    print(f"Market Cap: ${info.get('marketCap', 0):,}")
    print(f"Forward P/E: {info.get('forwardPE', 'N/A')}")
    print(f"Trailing P/E: {info.get('trailingPE', 'N/A')}")
    print(f"EPS: ${info.get('trailingEps', 'N/A')}")
    print(f"Forward EPS: ${info.get('forwardEps', 'N/A')}")
    print(f"ROE: {info.get('returnOnEquity', 'N/A')}")
    print(f"Revenue Growth: {info.get('revenueGrowth', 'N/A')}")
    print(f"Profit Margin: {info.get('profitMargins', 'N/A')}")

def get_history(ticker, period="1mo"):
    """Get historical price data and show ASCII trend"""
    stock = yf.Ticker(ticker)
    hist = stock.history(period=period)
    
    if hist.empty:
        print(f"No data found for {ticker}")
        return
    
    print(f"\n{ticker} Price History ({period}):")
    print(f"High: ${hist['High'].max():.2f}")
    print(f"Low: ${hist['Low'].min():.2f}")
    print(f"Average Volume: {hist['Volume'].mean():,.0f}")
    
    # Simple ASCII trend
    recent = hist.tail(10)
    print("\nRecent 10-day trend:")
    for i, (date, row) in enumerate(recent.iterrows()):
        direction = "▲" if row['Close'] > row['Open'] else "▼"
        print(f"{date.strftime('%m/%d')} {direction} ${row['Close']:.2f}")

def calculate_indicators(data, indicators):
    """Calculate technical indicators"""
    df = data.copy()
    
    if 'rsi' in indicators:
        # RSI calculation
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
    
    if 'macd' in indicators:
        # MACD calculation
        exp1 = df['Close'].ewm(span=12).mean()
        exp2 = df['Close'].ewm(span=26).mean()
        df['MACD'] = exp1 - exp2
        df['MACD_Signal'] = df['MACD'].ewm(span=9).mean()
        df['MACD_Histogram'] = df['MACD'] - df['MACD_Signal']
    
    if 'bb' in indicators:
        # Bollinger Bands
        df['BB_Middle'] = df['Close'].rolling(window=20).mean()
        bb_std = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['BB_Middle'] + (bb_std * 2)
        df['BB_Lower'] = df['BB_Middle'] - (bb_std * 2)
    
    if 'vwap' in indicators:
        # VWAP
        df['VWAP'] = (df['Volume'] * (df['High'] + df['Low'] + df['Close']) / 3).cumsum() / df['Volume'].cumsum()
    
    if 'atr' in indicators:
        # ATR
        df['TR1'] = df['High'] - df['Low']
        df['TR2'] = abs(df['High'] - df['Close'].shift())
        df['TR3'] = abs(df['Low'] - df['Close'].shift())
        df['True_Range'] = df[['TR1', 'TR2', 'TR3']].max(axis=1)
        df['ATR'] = df['True_Range'].rolling(window=14).mean()
    
    return df

def create_pro_chart(ticker, period="6mo", chart_type="candlestick", indicators=None):
    """Create professional chart with indicators"""
    if indicators is None:
        indicators = []
    
    stock = yf.Ticker(ticker)
    data = stock.history(period=period)
    
    if data.empty:
        print(f"No data found for {ticker}")
        return None
    
    # Calculate indicators
    data = calculate_indicators(data, indicators)
    
    # Create figure with subplots for indicators
    rows = 1 + len([i for i in indicators if i in ['rsi', 'macd', 'atr']])
    fig, axes = plt.subplots(rows, 1, figsize=(12, 4 * rows), sharex=True)
    
    if rows == 1:
        axes = [axes]
    
    # Main price chart
    ax = axes[0]
    
    if chart_type == "line":
        ax.plot(data.index, data['Close'], label='Close Price', linewidth=2)
    else:
        # Candlestick chart
        ax.plot(data.index, data['Close'], label='Close Price', alpha=0.7)
        # Simple candlestick representation
        for i, (date, row) in enumerate(data.iterrows()):
            color = 'green' if row['Close'] > row['Open'] else 'red'
            ax.plot([date, date], [row['Low'], row['High']], color='black', linewidth=1)
            ax.plot([date, date], [row['Open'], row['Close']], color=color, linewidth=3)
    
    # Add indicators to main chart
    if 'bb' in indicators:
        ax.plot(data.index, data['BB_Upper'], 'r--', alpha=0.7, label='BB Upper')
        ax.plot(data.index, data['BB_Lower'], 'r--', alpha=0.7, label='BB Lower')
        ax.fill_between(data.index, data['BB_Upper'], data['BB_Lower'], alpha=0.1, color='gray')
    
    if 'vwap' in indicators:
        ax.plot(data.index, data['VWAP'], 'purple', alpha=0.7, label='VWAP')
    
    ax.set_title(f'{ticker} - {period} Chart')
    ax.set_ylabel('Price ($)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Add RSI subplot
    current_row = 1
    if 'rsi' in indicators and current_row < len(axes):
        ax_rsi = axes[current_row]
        ax_rsi.plot(data.index, data['RSI'], 'blue', label='RSI')
        ax_rsi.axhline(y=70, color='r', linestyle='--', alpha=0.7, label='Overbought (70)')
        ax_rsi.axhline(y=30, color='g', linestyle='--', alpha=0.7, label='Oversold (30)')
        ax_rsi.set_ylabel('RSI')
        ax_rsi.legend()
        ax_rsi.grid(True, alpha=0.3)
        current_row += 1
    
    # Add MACD subplot
    if 'macd' in indicators and current_row < len(axes):
        ax_macd = axes[current_row]
        ax_macd.plot(data.index, data['MACD'], 'blue', label='MACD')
        ax_macd.plot(data.index, data['MACD_Signal'], 'red', label='Signal')
        ax_macd.bar(data.index, data['MACD_Histogram'], alpha=0.3, label='Histogram')
        ax_macd.set_ylabel('MACD')
        ax_macd.legend()
        ax_macd.grid(True, alpha=0.3)
        current_row += 1
    
    # Add ATR subplot
    if 'atr' in indicators and current_row < len(axes):
        ax_atr = axes[current_row]
        ax_atr.plot(data.index, data['ATR'], 'orange', label='ATR')
        ax_atr.set_ylabel('ATR')
        ax_atr.legend()
        ax_atr.grid(True, alpha=0.3)
    
    # Format x-axis
    axes[-1].xaxis.set_major_formatter(DateFormatter('%Y-%m-%d'))
    axes[-1].xaxis.set_major_locator(mdates.MonthLocator())
    plt.xticks(rotation=45)
    
    plt.tight_layout()
    
    # Save chart
    import tempfile
    temp_dir = tempfile.gettempdir()
    chart_path = f"{temp_dir}/{ticker}_{period}_pro_chart.png"
    plt.savefig(chart_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"Chart saved: {chart_path}")
    return chart_path

def generate_report(ticker, period="6mo"):
    """Generate comprehensive report"""
    print(f"\n=== {ticker} Stock Analysis Report ===\n")
    
    # Get current price
    get_price(ticker)
    print()
    
    # Get fundamentals
    get_fundamentals(ticker)
    print()
    
    # Get recent history
    get_history(ticker, "1mo")
    print()
    
    # Generate chart with common indicators
    chart_path = create_pro_chart(ticker, period, indicators=['rsi', 'macd', 'bb'])
    
    print(f"\nTechnical Analysis Summary:")
    print(f"Chart generated: {chart_path}")
    
    # Simple forecast based on recent trend
    stock = yf.Ticker(ticker)
    hist = stock.history(period="1mo")
    
    if not hist.empty:
        recent_trend = (hist['Close'].iloc[-1] - hist['Close'].iloc[-5]) / hist['Close'].iloc[-5] * 100
        volatility = hist['Close'].pct_change().std() * np.sqrt(252) * 100
        
        print(f"Recent 5-day trend: {recent_trend:.2f}%")
        print(f"Annualized volatility: {volatility:.1f}%")
        
        # Simple forecast (this is not financial advice!)
        current_price = hist['Close'].iloc[-1]
        forecast_range = current_price * (volatility / 100 / np.sqrt(52))  # Weekly volatility
        
        print(f"\nNext Week Price Forecast (based on volatility):")
        print(f"Expected range: ${current_price - forecast_range:.2f} - ${current_price + forecast_range:.2f}")
        print(f"Current price: ${current_price:.2f}")
    
    return chart_path

def main():
    parser = argparse.ArgumentParser(description='Stock Market Pro - Yahoo Finance Tool')
    parser.add_argument('command', choices=['price', 'fundamentals', 'history', 'pro', 'chart', 'report', 'option'])
    parser.add_argument('ticker', help='Stock ticker symbol')
    parser.add_argument('period', nargs='?', default='6mo', help='Time period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max)')
    parser.add_argument('--rsi', action='store_true', help='Add RSI indicator')
    parser.add_argument('--macd', action='store_true', help='Add MACD indicator')
    parser.add_argument('--bb', action='store_true', help='Add Bollinger Bands')
    parser.add_argument('--vwap', action='store_true', help='Add VWAP indicator')
    parser.add_argument('--atr', action='store_true', help='Add ATR indicator')
    parser.add_argument('--line', action='store_true', help='Use line chart instead of candlestick')
    
    args = parser.parse_args()
    
    try:
        if args.command == 'price':
            get_price(args.ticker)
        elif args.command == 'fundamentals':
            get_fundamentals(args.ticker)
        elif args.command == 'history':
            get_history(args.ticker, args.period)
        elif args.command in ['pro', 'chart']:
            indicators = []
            if args.rsi: indicators.append('rsi')
            if args.macd: indicators.append('macd')
            if args.bb: indicators.append('bb')
            if args.vwap: indicators.append('vwap')
            if args.atr: indicators.append('atr')
            
            chart_type = 'line' if args.line else 'candlestick'
            create_pro_chart(args.ticker, args.period, chart_type, indicators)
        elif args.command == 'report':
            generate_report(args.ticker, args.period)
        elif args.command == 'option':
            print("Options data requires browser access. Use:")
            print(f"https://unusualwhales.com/stock/{args.ticker}/overview")
            print(f"https://unusualwhales.com/live-options-flow?ticker_symbol={args.ticker}")
    
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()