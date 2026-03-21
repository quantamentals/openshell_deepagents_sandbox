import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

def get_wmt_historical_data(period="1y"):
    """
    Fetch historical price data for WMT (Walmart) stock.
    
    Args:
        period (str): Data period - '1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max'
    
    Returns:
        pandas.DataFrame: Historical price data with OHLCV columns
    """
    # Create ticker object for WMT
    wmt = yf.Ticker("WMT")
    
    # Fetch historical data
    hist_data = wmt.history(period=period)
    
    # Display basic info
    print(f"WMT Historical Data ({period})")
    print(f"Data shape: {hist_data.shape}")
    print(f"Date range: {hist_data.index.min()} to {hist_data.index.max()}")
    print("\nFirst 5 rows:")
    print(hist_data.head())
    print("\nLast 5 rows:")
    print(hist_data.tail())
    
    return hist_data

def get_wmt_historical_data_custom(start_date, end_date):
    """
    Fetch historical price data for WMT with custom date range.
    
    Args:
        start_date (str): Start date in 'YYYY-MM-DD' format
        end_date (str): End date in 'YYYY-MM-DD' format
    
    Returns:
        pandas.DataFrame: Historical price data with OHLCV columns
    """
    # Create ticker object for WMT
    wmt = yf.Ticker("WMT")
    
    # Fetch historical data
    hist_data = wmt.history(start=start_date, end=end_date)
    
    # Display basic info
    print(f"WMT Historical Data ({start_date} to {end_date})")
    print(f"Data shape: {hist_data.shape}")
    print(f"Date range: {hist_data.index.min()} to {hist_data.index.max()}")
    print("\nFirst 5 rows:")
    print(hist_data.head())
    print("\nLast 5 rows:")
    print(hist_data.tail())
    
    return hist_data

if __name__ == "__main__":
    # Get 1 year of historical data by default
    print("Fetching WMT historical price data...")
    wmt_data = get_wmt_historical_data("1y")
    
    # Optionally save to CSV
    wmt_data.to_csv("outputs/wmt_historical_data.csv")
    print("\nData saved to outputs/wmt_historical_data.csv")