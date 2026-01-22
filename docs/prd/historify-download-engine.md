# Historify Download Engine

Complete documentation for the bulk download job management system.

## Overview

The download engine handles data retrieval from broker APIs with rate limiting, job tracking, and progress reporting.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Download Request                                     │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  POST /api/v1/historify/download                                        ││
│  │  {symbols: [...], start_date, end_date, interval}                       ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Job Manager                                           │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  1. Create download_job record (status: pending)                        ││
│  │  2. Create job_items for each symbol                                    ││
│  │  3. Queue job for execution                                             ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Download Worker (Background Thread)                     │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  For each job_item:                                                     ││
│  │    1. Check rate limiter                                                ││
│  │    2. Fetch data from broker API                                        ││
│  │    3. Transform to standard format                                      ││
│  │    4. Insert into DuckDB                                                ││
│  │    5. Update job_item status                                            ││
│  │    6. Emit progress via WebSocket                                       ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
┌───────────────────┐ ┌───────────────┐ ┌───────────────┐
│   Broker API      │ │   DuckDB      │ │   WebSocket   │
│   (Rate Limited)  │ │   Storage     │ │   Progress    │
└───────────────────┘ └───────────────┘ └───────────────┘
```

## Job States

```
┌─────────┐
│ pending │ ──▶ Job created, waiting to start
└────┬────┘
     │
     ▼
┌─────────┐
│ running │ ──▶ Actively downloading data
└────┬────┘
     │
     ├───────────────┐
     ▼               ▼
┌─────────┐     ┌────────┐
│ paused  │     │ failed │ ──▶ Unrecoverable error
└────┬────┘     └────────┘
     │
     ▼
┌───────────┐
│ completed │ ──▶ All items processed
└───────────┘
```

## Job Item States

| State | Description |
|-------|-------------|
| `pending` | Waiting to be processed |
| `downloading` | Currently fetching data |
| `completed` | Successfully downloaded |
| `failed` | Download failed (with error) |
| `skipped` | Skipped (e.g., no data available) |

## Download Worker

### Worker Loop

```python
class DownloadWorker:
    def __init__(self):
        self._running = False
        self._current_job = None
        self._rate_limiter = RateLimiter(requests_per_second=5)

    def start(self):
        """Start the download worker thread"""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        """Main worker loop"""
        while self._running:
            # Get next pending job
            job = self._get_next_job()

            if job:
                self._process_job(job)
            else:
                time.sleep(1)  # Wait for new jobs

    def _process_job(self, job):
        """Process a single download job"""
        self._current_job = job
        job.status = 'running'
        job.started_at = datetime.now()
        db.session.commit()

        # Get pending items
        items = JobItem.query.filter_by(
            job_id=job.id,
            status='pending'
        ).all()

        for item in items:
            if not self._running or job.status == 'paused':
                break

            self._process_item(job, item)

        # Update job status
        if job.status != 'paused':
            failed = JobItem.query.filter_by(job_id=job.id, status='failed').count()
            job.status = 'failed' if failed == len(items) else 'completed'
            job.completed_at = datetime.now()
            db.session.commit()

        self._current_job = None
```

### Item Processing

```python
def _process_item(self, job, item):
    """Process a single job item (symbol)"""
    item.status = 'downloading'
    item.started_at = datetime.now()
    db.session.commit()

    try:
        # Wait for rate limiter
        self._rate_limiter.wait()

        # Fetch from broker
        data = self._fetch_from_broker(
            symbol=item.symbol,
            exchange=item.exchange,
            interval=job.interval,
            start_date=job.start_date,
            end_date=job.end_date
        )

        if data is None or len(data) == 0:
            item.status = 'skipped'
            item.error_message = 'No data available'
        else:
            # Insert into DuckDB
            self._insert_data(item.symbol, item.exchange, job.interval, data)
            item.status = 'completed'
            item.records_downloaded = len(data)

    except Exception as e:
        item.status = 'failed'
        item.error_message = str(e)
        logger.error(f"Download failed for {item.symbol}: {e}")

    finally:
        item.completed_at = datetime.now()
        job.completed_items += 1
        if item.status == 'failed':
            job.failed_items += 1
        db.session.commit()

        # Emit progress
        self._emit_progress(job)
```

## Rate Limiting

### Token Bucket Algorithm

```python
class RateLimiter:
    def __init__(self, requests_per_second=5):
        self.rate = requests_per_second
        self.tokens = requests_per_second
        self.last_update = time.time()
        self._lock = threading.Lock()

    def wait(self):
        """Wait until a request token is available"""
        with self._lock:
            now = time.time()
            elapsed = now - self.last_update
            self.last_update = now

            # Add tokens based on elapsed time
            self.tokens = min(self.rate, self.tokens + elapsed * self.rate)

            if self.tokens < 1:
                # Wait for token to become available
                wait_time = (1 - self.tokens) / self.rate
                time.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1
```

### Broker-Specific Limits

| Broker | Requests/Second | Daily Limit |
|--------|-----------------|-------------|
| Zerodha | 3 | 10,000 |
| Angel | 5 | Unlimited |
| Dhan | 10 | Unlimited |
| Fyers | 5 | 5,000 |

## Broker Data Fetching

### Universal Fetch Function

```python
def _fetch_from_broker(self, symbol, exchange, interval, start_date, end_date):
    """Fetch historical data from broker"""
    from broker.common.api import get_broker_api

    api = get_broker_api()

    # Map interval to broker format
    broker_interval = self._map_interval(interval)

    # Chunk large date ranges (broker limits)
    chunks = self._chunk_date_range(start_date, end_date)

    all_data = []
    for chunk_start, chunk_end in chunks:
        data = api.history(
            symbol=symbol,
            exchange=exchange,
            interval=broker_interval,
            start_date=chunk_start,
            end_date=chunk_end
        )

        if data:
            all_data.extend(data)

    return all_data
```

### Date Range Chunking

```python
def _chunk_date_range(self, start_date, end_date, max_days=90):
    """Split large date ranges into chunks"""
    chunks = []
    current = start_date

    while current < end_date:
        chunk_end = min(current + timedelta(days=max_days), end_date)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)

    return chunks
```

## Progress Reporting

### WebSocket Events

```python
def _emit_progress(self, job):
    """Emit job progress via WebSocket"""
    progress = {
        'job_id': job.id,
        'status': job.status,
        'total': job.total_items,
        'completed': job.completed_items,
        'failed': job.failed_items,
        'percent': (job.completed_items / job.total_items * 100) if job.total_items > 0 else 0,
        'current_symbol': self._current_item.symbol if self._current_item else None
    }

    socketio.emit('historify_progress', progress, namespace='/historify')
```

### Client-Side Listener

```javascript
socket.on('historify_progress', (data) => {
    console.log(`Job ${data.job_id}: ${data.percent}% complete`);
    console.log(`Downloading: ${data.current_symbol}`);

    // Update progress bar
    updateProgressBar(data.percent);

    if (data.status === 'completed') {
        showNotification('Download complete!');
    }
});
```

## Job Management

### Pause Job

```python
def pause_job(job_id):
    """Pause a running job"""
    job = DownloadJob.query.get(job_id)
    if job and job.status == 'running':
        job.status = 'paused'
        db.session.commit()
        return True, "Job paused"
    return False, "Job not running"
```

### Resume Job

```python
def resume_job(job_id):
    """Resume a paused job"""
    job = DownloadJob.query.get(job_id)
    if job and job.status == 'paused':
        job.status = 'pending'  # Worker will pick it up
        db.session.commit()

        # Wake up worker
        worker.notify()
        return True, "Job resumed"
    return False, "Job not paused"
```

### Cancel Job

```python
def cancel_job(job_id):
    """Cancel a job"""
    job = DownloadJob.query.get(job_id)
    if job and job.status in ['pending', 'running', 'paused']:
        job.status = 'cancelled'
        job.completed_at = datetime.now()
        db.session.commit()
        return True, "Job cancelled"
    return False, "Cannot cancel job"
```

## Incremental Downloads

### Check Existing Data

```python
def get_missing_ranges(symbol, exchange, interval, start_date, end_date):
    """Find missing date ranges for incremental download"""
    with get_connection() as conn:
        catalog = conn.execute("""
            SELECT first_date, last_date
            FROM data_catalog
            WHERE symbol = ? AND exchange = ? AND interval = ?
        """, [symbol, exchange, interval]).fetchone()

        if catalog is None:
            return [(start_date, end_date)]

        missing = []

        # Check if data before existing range needed
        if start_date < catalog['first_date']:
            missing.append((start_date, catalog['first_date'] - timedelta(days=1)))

        # Check if data after existing range needed
        if end_date > catalog['last_date']:
            missing.append((catalog['last_date'] + timedelta(days=1), end_date))

        return missing
```

### Smart Download

```python
def download_incremental(symbol, exchange, interval, start_date, end_date):
    """Download only missing data"""
    missing_ranges = get_missing_ranges(symbol, exchange, interval, start_date, end_date)

    for range_start, range_end in missing_ranges:
        data = fetch_from_broker(symbol, exchange, interval, range_start, range_end)
        insert_data(symbol, exchange, interval, data)

    # Update catalog
    update_data_catalog(symbol, exchange, interval)
```

## F&O Discovery

### Get Option Chain

```python
def download_option_chain(underlying, expiry, start_date, end_date):
    """Download all strikes for an expiry"""
    # Get available strikes
    strikes = get_option_strikes(underlying, expiry)

    symbols = []
    for strike in strikes:
        for option_type in ['CE', 'PE']:
            symbol = f"{underlying}{expiry.strftime('%d%b%y').upper()}{strike}{option_type}"
            symbols.append({
                'symbol': symbol,
                'exchange': 'NFO',
                'underlying': underlying,
                'strike': strike,
                'option_type': option_type,
                'expiry': expiry
            })

    # Create bulk download job
    return create_download_job(symbols, start_date, end_date, interval='1m')
```

## Error Handling

### Retry Logic

```python
def _fetch_with_retry(self, symbol, exchange, interval, start_date, end_date, max_retries=3):
    """Fetch with exponential backoff retry"""
    for attempt in range(max_retries):
        try:
            return self._fetch_from_broker(symbol, exchange, interval, start_date, end_date)
        except RateLimitError:
            wait_time = 2 ** attempt
            logger.warning(f"Rate limited, waiting {wait_time}s")
            time.sleep(wait_time)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"Attempt {attempt + 1} failed: {e}")
            time.sleep(1)
```

### Error Categories

| Error Type | Handling |
|------------|----------|
| Rate limit | Exponential backoff |
| Network error | Retry 3 times |
| Invalid symbol | Skip, mark failed |
| No data | Skip, mark as skipped |
| Auth error | Fail job, notify user |

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `HISTORIFY_RATE_LIMIT` | 5 | Requests per second |
| `HISTORIFY_MAX_CHUNK_DAYS` | 90 | Max days per API request |
| `HISTORIFY_MAX_RETRIES` | 3 | Retry attempts on failure |
| `HISTORIFY_WORKER_THREADS` | 1 | Number of download workers |

## Related Documentation

| Document | Description |
|----------|-------------|
| [Historify PRD](./historify.md) | Product requirements |
| [Data Model](./historify-data-model.md) | DuckDB schema |
| [API Reference](./historify-api-reference.md) | Complete API documentation |
