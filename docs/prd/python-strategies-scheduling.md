# Python Strategies Scheduling

Complete documentation for APScheduler integration and market-aware scheduling.

## Overview

Python strategies use APScheduler with IST timezone support to automatically start/stop based on market hours.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         APScheduler                                          │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │              BackgroundScheduler (timezone='Asia/Kolkata')              ││
│  │                                                                          ││
│  │  Jobs:                                                                   ││
│  │  ┌──────────────────────────────────────────────────────────────────┐  ││
│  │  │ daily_trading_day_check    │ Cron: 00:01 daily                   │  ││
│  │  │ market_hours_enforcer      │ Interval: 1 minute                  │  ││
│  │  │ strategy_start_job_<id>    │ Cron: 09:20 Mon-Fri                │  ││
│  │  │ strategy_stop_job_<id>     │ Cron: 15:15 Mon-Fri                │  ││
│  │  └──────────────────────────────────────────────────────────────────┘  ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Market Calendar                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  is_trading_day()                                                        ││
│  │    │                                                                     ││
│  │    ├── Check weekday (Mon-Fri for equity)                               ││
│  │    │                                                                     ││
│  │    └── Check holiday calendar (NSE holidays)                            ││
│  │                                                                          ││
│  │  Market Hours:                                                           ││
│  │    NSE/BSE: 09:15 - 15:30                                               ││
│  │    MCX: 09:00 - 23:30                                                   ││
│  │    CDS: 09:00 - 17:00                                                   ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

## Scheduler Initialization

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

IST = pytz.timezone('Asia/Kolkata')

# Initialize scheduler with IST timezone
SCHEDULER = BackgroundScheduler(timezone=IST)

def initialize_scheduler():
    """Initialize the strategy scheduler"""
    if not SCHEDULER.running:
        SCHEDULER.start()

        # Add daily trading day check (00:01 IST)
        SCHEDULER.add_job(
            func=daily_trading_day_check,
            trigger=CronTrigger(hour=0, minute=1, timezone=IST),
            id='daily_trading_day_check',
            replace_existing=True
        )

        # Add market hours enforcer (every minute)
        SCHEDULER.add_job(
            func=market_hours_enforcer,
            trigger='interval',
            minutes=1,
            id='market_hours_enforcer',
            replace_existing=True
        )
```

## Schedule Configuration

### User Interface

```
┌─────────────────────────────────────────────────────────────┐
│  Strategy Schedule Configuration                             │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Start Time: [09:20] IST                                    │
│  Stop Time:  [15:15] IST                                    │
│                                                              │
│  Trading Days:                                               │
│  [✓] Monday                                                  │
│  [✓] Tuesday                                                 │
│  [✓] Wednesday                                               │
│  [✓] Thursday                                                │
│  [✓] Friday                                                  │
│  [ ] Saturday                                                │
│                                                              │
│  [Save Schedule] [Clear Schedule]                           │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Schedule Storage

```json
{
  "my_strategy": {
    "is_scheduled": true,
    "schedule_start": "09:20",
    "schedule_stop": "15:15",
    "schedule_days": ["mon", "tue", "wed", "thu", "fri"]
  }
}
```

## Job Creation

### Add Schedule

```python
def schedule_strategy(strategy_id, start_time, stop_time, days):
    """Schedule strategy for automatic start/stop"""

    # Parse time
    start_hour, start_minute = map(int, start_time.split(':'))
    stop_hour, stop_minute = map(int, stop_time.split(':'))

    # Map day names to cron day-of-week values
    day_map = {
        'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3,
        'fri': 4, 'sat': 5, 'sun': 6
    }
    cron_days = ','.join(str(day_map[d]) for d in days)

    # Create start job
    SCHEDULER.add_job(
        func=scheduled_start_strategy,
        trigger=CronTrigger(
            hour=start_hour,
            minute=start_minute,
            day_of_week=cron_days,
            timezone=IST
        ),
        args=[strategy_id],
        id=f'strategy_start_{strategy_id}',
        replace_existing=True
    )

    # Create stop job
    SCHEDULER.add_job(
        func=scheduled_stop_strategy,
        trigger=CronTrigger(
            hour=stop_hour,
            minute=stop_minute,
            day_of_week=cron_days,
            timezone=IST
        ),
        args=[strategy_id],
        id=f'strategy_stop_{strategy_id}',
        replace_existing=True
    )

    # Update config
    update_strategy_config(strategy_id, {
        'is_scheduled': True,
        'schedule_start': start_time,
        'schedule_stop': stop_time,
        'schedule_days': days
    })
```

### Remove Schedule

```python
def unschedule_strategy(strategy_id):
    """Remove scheduled jobs for strategy"""

    # Remove start job
    if SCHEDULER.get_job(f'strategy_start_{strategy_id}'):
        SCHEDULER.remove_job(f'strategy_start_{strategy_id}')

    # Remove stop job
    if SCHEDULER.get_job(f'strategy_stop_{strategy_id}'):
        SCHEDULER.remove_job(f'strategy_stop_{strategy_id}')

    # Update config
    update_strategy_config(strategy_id, {
        'is_scheduled': False
    })
```

## Market Calendar Integration

### Trading Day Check

```python
def is_trading_day(date=None):
    """Check if given date is a trading day"""
    if date is None:
        date = datetime.now(IST).date()

    # Check weekday (0=Monday, 6=Sunday)
    if date.weekday() >= 5:  # Saturday or Sunday
        return False

    # Check against holiday calendar
    holidays = get_market_holidays(date.year)
    if date in holidays:
        return False

    return True
```

### Daily Trading Day Check

```python
def daily_trading_day_check():
    """
    Runs at 00:01 IST daily.
    Stops all scheduled strategies if not a trading day.
    """
    today = datetime.now(IST).date()

    if not is_trading_day(today):
        logger.info(f"Non-trading day detected: {today}")

        # Stop all scheduled strategies
        for strategy_id, config in get_all_configs().items():
            if config.get('is_scheduled') and config.get('is_running'):
                stop_strategy(strategy_id)
                update_strategy_config(strategy_id, {
                    'manually_stopped': False  # Will auto-resume
                })
```

### Market Hours Enforcer

```python
def market_hours_enforcer():
    """
    Runs every minute.
    Ensures strategies stop after market hours even if stop job missed.
    """
    now = datetime.now(IST)
    current_time = now.time()

    for strategy_id, config in get_all_configs().items():
        if not config.get('is_scheduled') or not config.get('is_running'):
            continue

        stop_time = datetime.strptime(config['schedule_stop'], '%H:%M').time()

        # If past stop time, stop strategy
        if current_time > stop_time:
            logger.info(f"Enforcing stop for {strategy_id} (past {stop_time})")
            stop_strategy(strategy_id)
```

## Holiday Calendar

### NSE Holiday List

```python
NSE_HOLIDAYS_2024 = [
    date(2024, 1, 26),   # Republic Day
    date(2024, 3, 8),    # Mahashivratri
    date(2024, 3, 25),   # Holi
    date(2024, 3, 29),   # Good Friday
    date(2024, 4, 11),   # Id-Ul-Fitr
    date(2024, 4, 14),   # Dr. Ambedkar Jayanti
    date(2024, 4, 17),   # Ram Navami
    date(2024, 4, 21),   # Mahavir Jayanti
    date(2024, 5, 1),    # Maharashtra Day
    date(2024, 5, 23),   # Buddha Purnima
    date(2024, 6, 17),   # Eid
    date(2024, 7, 17),   # Muharram
    date(2024, 8, 15),   # Independence Day
    date(2024, 10, 2),   # Mahatma Gandhi Jayanti
    date(2024, 11, 1),   # Diwali-Laxmi Pujan
    date(2024, 11, 15),  # Gurunanak Jayanti
    date(2024, 12, 25),  # Christmas
]

def get_market_holidays(year):
    """Get holiday list for given year"""
    if year == 2024:
        return NSE_HOLIDAYS_2024
    # Fetch from API or database for other years
    return fetch_holidays_from_api(year)
```

## Scheduled Job Handlers

### Scheduled Start

```python
def scheduled_start_strategy(strategy_id):
    """Handler for scheduled strategy start"""
    config = get_strategy_config(strategy_id)

    # Skip if manually stopped by user
    if config.get('manually_stopped'):
        logger.info(f"Skipping scheduled start for {strategy_id} (manually stopped)")
        return

    # Skip if not a trading day
    if not is_trading_day():
        logger.info(f"Skipping scheduled start for {strategy_id} (non-trading day)")
        return

    # Skip if already running
    if config.get('is_running'):
        logger.debug(f"Strategy {strategy_id} already running")
        return

    # Start the strategy
    logger.info(f"Scheduled start: {strategy_id}")
    start_strategy(strategy_id)
```

### Scheduled Stop

```python
def scheduled_stop_strategy(strategy_id):
    """Handler for scheduled strategy stop"""
    config = get_strategy_config(strategy_id)

    # Skip if not running
    if not config.get('is_running'):
        logger.debug(f"Strategy {strategy_id} not running")
        return

    # Stop the strategy
    logger.info(f"Scheduled stop: {strategy_id}")
    stop_strategy(strategy_id)

    # Mark as not manually stopped (for next day auto-start)
    update_strategy_config(strategy_id, {
        'manually_stopped': False
    })
```

## Job Persistence

### Restore Jobs on Restart

```python
def restore_scheduled_jobs():
    """Restore scheduled jobs from config after app restart"""
    for strategy_id, config in get_all_configs().items():
        if config.get('is_scheduled'):
            schedule_strategy(
                strategy_id,
                config['schedule_start'],
                config['schedule_stop'],
                config['schedule_days']
            )
            logger.info(f"Restored schedule for {strategy_id}")
```

### Scheduler State

```python
def get_scheduler_status():
    """Get current scheduler status"""
    jobs = []
    for job in SCHEDULER.get_jobs():
        jobs.append({
            'id': job.id,
            'name': job.name,
            'next_run': job.next_run_time.isoformat() if job.next_run_time else None,
            'trigger': str(job.trigger)
        })

    return {
        'running': SCHEDULER.running,
        'job_count': len(jobs),
        'jobs': jobs
    }
```

## Timeline Example

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Monday, January 15, 2024 (Trading Day)                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  00:01  daily_trading_day_check() runs                                      │
│         → Is Monday, not a holiday → Trading day confirmed                  │
│                                                                              │
│  09:20  strategy_start_ema_crossover job fires                              │
│         → scheduled_start_strategy('ema_crossover')                         │
│         → Strategy subprocess started (PID: 12345)                          │
│         → Log streaming begins                                               │
│                                                                              │
│  09:21  market_hours_enforcer() runs (every minute)                         │
│  09:22  market_hours_enforcer() runs                                        │
│  ...                                                                         │
│                                                                              │
│  15:15  strategy_stop_ema_crossover job fires                               │
│         → scheduled_stop_strategy('ema_crossover')                          │
│         → SIGTERM sent to process group                                     │
│         → Process terminated gracefully                                      │
│                                                                              │
│  15:16  market_hours_enforcer() runs                                        │
│         → Confirms all strategies stopped                                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  Saturday, January 20, 2024 (Weekend)                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  00:01  daily_trading_day_check() runs                                      │
│         → Is Saturday → NOT a trading day                                   │
│         → All scheduled strategies remain stopped                           │
│                                                                              │
│  09:20  strategy_start_ema_crossover job fires                              │
│         → scheduled_start_strategy('ema_crossover')                         │
│         → is_trading_day() returns False                                    │
│         → Start skipped                                                     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Troubleshooting

### Common Issues

| Issue | Cause | Resolution |
|-------|-------|------------|
| Strategy doesn't start at scheduled time | Holiday or weekend | Check `is_trading_day()` |
| Strategy starts but immediately stops | Stop time before start time | Fix schedule config |
| Jobs lost after restart | `restore_scheduled_jobs()` not called | Add to app startup |
| Wrong timezone | System timezone mismatch | Ensure IST is used |

### Debug Commands

```python
# Check next run time for a job
job = SCHEDULER.get_job('strategy_start_ema_crossover')
print(f"Next run: {job.next_run_time}")

# List all jobs
for job in SCHEDULER.get_jobs():
    print(f"{job.id}: {job.next_run_time}")

# Check if scheduler is running
print(f"Scheduler running: {SCHEDULER.running}")
```

## Related Documentation

| Document | Description |
|----------|-------------|
| [Python Strategies PRD](./python-strategies.md) | Product requirements |
| [Process Management](./python-strategies-process-management.md) | Subprocess handling |
| [API Reference](./python-strategies-api-reference.md) | Complete API docs |
