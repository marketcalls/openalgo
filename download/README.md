# IEOD Data Downloader

This tool allows you to download Intraday End of Day (IEOD) data for specified stock symbols from the OpenAlgo API.

## Prerequisites

- Python 3.x
- Valid OpenAlgo API key
- Access to OpenAlgo API endpoint (ensure openalgo is running)

## File Structure

- `ieod.py`: Main script for downloading IEOD data
- `symbols.csv`: List of stock symbols to download data for
- `checkpoint.txt`: Tracks download progress (automatically created)
- `data_download.log`: Log file for download operations (automatically created)

## Setup

1. Ensure you have a valid API key from OpenAlgo
2. Place your stock symbols in `symbols.csv` (one symbol per line)
3. The script will automatically create necessary folders and files

## Usage

Run the script using Python:

```bash
python ieod.py
```

### Download Options

The script provides two modes of operation:

1. Fresh Download
2. Continue from Last Checkpoint

### Time Period Options

You can select from various time periods for data download:

1. Today's Data
2. Last 5 Days Data
3. Last 30 Days Data
4. Last 90 Days Data
5. Last 1 Year Data
6. Last 2 Years Data
7. Last 5 Years Data
8. Last 10 Years Data

### Output

- Downloaded data is saved in the `symbols` folder
- Each symbol's data is saved in a separate CSV file
- Progress is tracked in `checkpoint.txt`
- Download logs are saved in `data_download.log`

## symbols.csv Format

The `symbols.csv` file should contain one stock symbol per line. Example:

```
RELIANCE
ICICIBANK
HDFCBANK
SBIN
TCS
INFY
```

## Error Handling

- The script includes error handling and logging
- Failed downloads are logged in `data_download.log`
- The checkpoint system allows resuming interrupted downloads

## Notes

- Data is downloaded in batches to manage memory efficiently
- Default batch size is 10 symbols (adjustable in the code)
- The script includes rate limiting to prevent API overload
