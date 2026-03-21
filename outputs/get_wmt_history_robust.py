import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import sys

def get_wmt_historical_data(period="1y"):
    """
    Fetch historical price data for WMT (Walmart) stock with error handling.
    
    Args:
        period (str): Data period - '1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max'
    
    Returns:
        pandas.DataFrame: Historical price data with OHLCV columns or None if failed
    """
    try:
        # Create ticker object for WMT
        wmt = yf.Ticker("WMT")
        
        # Fetch historical data
        hist_data = wmt.history(period=period)
        
        if hist_data.empty:
            print("No data returned for WMT. This might be due to network restrictions.")
            return None
            
        # Display basic info
        print(f"WMT Historical Data ({period})")
        print(f"Data shape: {hist_data.shape}")
        print(f"Date range: {hist_data.index.min()} to {hist_data.index.max()}")
        print("\nFirst 5 rows:")
        print(hist_data.head())
        print("\nLast 5 rows:")
        print(hist_data.tail())
        
        return hist_data
        
    except Exception as e:
        print(f"Error fetching WMT data: {str(e)}")
        print("This appears to be a network connectivity issue preventing access to Yahoo Finance.")
        print("Possible solutions:")
        print("1. Check your network connection and firewall settings")
        print("2. Try using a VPN or different network")
        print("3. Consider using alternative data sources like Alpha Vantage or IEX Cloud")
        print("4. For testing purposes, you can use sample data instead")
        return None

def create_sample_wmt_data():
    """
    Create sample WMT data for demonstration purposes when real data can't be fetched.
    
    Returns:
        pandas.DataFrame: Sample historical price data
    """
    import numpy as np
    
    # Create sample data for the last 252 trading days (approx 1 year)
    dates = pd.date_range(end=datetime.now(), periods=252, freq='B')
    
    # Generate realistic price data for WMT (typically trades around $150-180)
    np.random.seed(42)  # For reproducible results
    base_price = 165
    returns = np.random.normal(0.0005, 0.02, len(dates))  # Daily returns
    prices = [base_price]
    
    for ret in returns[1:]:
        prices.append(prices[-1] * (1 + ret))
    
    # Create OHLCV data
    df = pd.DataFrame(index=dates)
    df['Close'] = prices
    df['Open'] = df['Close'] * (1 + np.random.normal(-0.005, 0.01, len(df)))
    df['High'] = np.maximum(df['Open'], df['Close']) * (1 + np.abs(np.random.normal(0, 0.015, len(df))))
    df['Low'] = np.minimum(df['Open'], df['Close']) * (1 - np.abs(np.random.normal(0, 0.015, len(df))))
    df['Volume'] = np.random.randint(5_000_000, 15_000_000, len(df))
    
    # Ensure High >= Low and High >= Open,Close and Low <= Open,Close
    df['High'] = np.maximum(df['High'], np.maximum(df['Open'], df['Close']))
    df['Low'] = np.minimum(df['Low'], np.minimum(df['Open'], df['Close']))
    
    print("Generated sample WMT data for demonstration purposes")
    print(f"Data shape: {df.shape}")
    print(f"Date range: {df.index.min()} to {df.index.max()}")
    print("\nFirst 5 rows:")
    print(df.head())
    print("\nLast 5 rows:")
    print(df.tail())
    
    return df

if __name__ == "__main__":
    print("Attempting to fetch WMT historical price data...")
    wmt_data = get_wmt_historical_data("1y")
    
    if wmt_data is None:
        print("\nFalling back to sample data for demonstration...")
        wmt_data = create_sample_wmt_data()
        
        # Save sample data to CSV
        wmt_data.to_csv("/sandbox/outputs/wmt_sample_data.csv")
        print("\nSample data saved to /sandbox/outputs/wmt_sample_data.csv")
    else:
        # Save real data to CSV
        wmt_data.to_csv("/sandbox/outputs/wmt_historical_data.csv")
        print("\nReal data saved to /sandbox/outputs/wmt_historical_data.csv")