import datetime

def add_days(base_date: datetime.date, days: int) -> datetime.date:
    return base_date + datetime.timedelta(days=days)

def add_months(base_date: datetime.date, months: int) -> datetime.date:
    """Adds months safely, clamping the day to the end of the target month."""
    month = base_date.month - 1 + months
    year = base_date.year + month // 12
    month = month % 12 + 1
    
    # Days in month
    is_leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days_in_month = [31, 29 if is_leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    
    day = min(base_date.day, days_in_month[month - 1])
    return datetime.date(year, month, day)

