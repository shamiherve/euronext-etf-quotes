"""Public Euronext XPAR delayed trades; Python standard library only."""
import argparse
import csv
import io
import json
import math
import os
from pathlib import Path
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import zipfile

INSTRUMENTS = {'FR0011550185': 'ESE', 'FR0011550193': 'ETZ', 'FR0013411980': 'PTPXE', 'FR0013412020': 'PAEEM'}
URL = 'https://marketdata.euronext.com/data-reporting-service/trades-file/download/ETFS_FUNDS/SINCE_PREVIOUS_TRADING_DAY/PAR'
FIELDS = {'isin', 'ticker', 'price', 'currency', 'trade_timestamp', 'update_timestamp'}
PARIS = ZoneInfo('Europe/Paris')
CLOSED = {2026: {'2026-01-01', '2026-04-03', '2026-04-06', '2026-05-01', '2026-12-25'},
          2027: {'2027-01-01', '2027-03-26', '2027-03-29'}}
MAX_ZIP = 32 * 1024 * 1024
MAX_CSV = 256 * 1024 * 1024
REQUIRED = {'MifidInstrumentID', 'MifidPrice', 'MifidQuantity', 'MifidCurrency', 'MifidPriceNotation',
            'TradingDateTime', 'PublicationDateTime', 'Venue', 'TradeUniqueIdentifier',
            'MmtModificationIndicator', 'MmtContributionToPrice', 'MissingPrice'}

def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('Timestamp must have a timezone')
    return parsed.astimezone(timezone.utc)

def stamp(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

def should_run(now, scheduled_cron=''):
    """Accept any trigger after the Paris close; GitHub often delays cron runs by hours."""
    local = now.astimezone(PARIS)
    if 9 <= local.hour < 18:
        return False  # market session in progress: never publish intraday trades
    session = local.date() if local.hour >= 18 else (local - timedelta(days=1)).date()
    if session.year not in CLOSED:
        raise ValueError('Review official Euronext calendar for this year before scheduling')
    return session.weekday() < 5 and session.isoformat() not in CLOSED[session.year]

def download():
    request = Request(URL, headers={'User-Agent': 'euronext-etf-quotes/1.0 (daily delayed public data)', 'Accept': 'application/zip'})
    with urlopen(request, timeout=90) as response:
        data = response.read(MAX_ZIP + 1)
    if len(data) > MAX_ZIP:
        raise ValueError('Download exceeds safe archive limit')
    return data

def read_previous(path):
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError('Invalid previous quote file')
    result = {}
    for q in data:
        if set(q) != FIELDS or q['isin'] not in INSTRUMENTS or q['isin'] in result:
            raise ValueError('Invalid quote identity/schema')
        if q['ticker'] != INSTRUMENTS[q['isin']] or q['currency'] != 'EUR':
            raise ValueError('Invalid quote currency/ticker')
        if isinstance(q['price'], bool) or not isinstance(q['price'], (int, float)) or not math.isfinite(q['price']) or q['price'] <= 0:
            raise ValueError('Invalid previous price')
        if timestamp(q['trade_timestamp']) > timestamp(q['update_timestamp']):
            raise ValueError('Invalid previous timestamps')
        result[q['isin']] = q
    return result

def parse_archive(data, now):
    if len(data) > MAX_ZIP:
        raise ValueError('Archive too large')
    records = {}
    invalidated = set()
    count = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) != 1 or infos[0].filename != 'Trades_ETFSFunds.csv' or infos[0].file_size > MAX_CSV:
            raise ValueError('Unexpected archive structure or size')
        with io.TextIOWrapper(archive.open(infos[0]), encoding='utf-8-sig', newline='') as stream:
            first = stream.readline()
            if not first.startswith('(c)'):
                raise ValueError('Missing Euronext copyright preamble')
            reader = csv.DictReader(stream)
            if not REQUIRED.issubset(reader.fieldnames or []):
                raise ValueError('Euronext CSV schema changed')
            for row in reader:
                count += 1
                isin = row['MifidInstrumentID']
                if isin not in INSTRUMENTS:
                    continue
                uid = row['TradeUniqueIdentifier'].strip()
                key = (isin, row['Venue'], uid)
                # Fail closed for all modification flags; tombstone matching originals.
                if row['MmtModificationIndicator'].strip() not in ('', '-'):
                    if uid:
                        invalidated.add(key)
                    continue
                if row['Venue'] != 'XPAR' or row['MifidCurrency'] != 'EUR' or row['MifidPriceNotation'] != 'MONE':
                    continue
                if row['MmtContributionToPrice'].strip() not in ('', '-') or row['MissingPrice'].strip() not in ('', '-') or not uid:
                    continue
                try:
                    price = Decimal(row['MifidPrice'])
                    quantity = Decimal(row['MifidQuantity'])
                    trade = timestamp(row['TradingDateTime'])
                    published = timestamp(row['PublicationDateTime'])
                    if not price.is_finite() or price <= 0 or not quantity.is_finite() or quantity <= 0:
                        continue
                    if trade > published or published > now:
                        continue
                    record = (trade, published, price)
                    if key in records and records[key] != record:
                        invalidated.add(key)
                    else:
                        records[key] = record
                except (ValueError, TypeError, InvalidOperation, OverflowError):
                    continue
    candidates = {}
    for key, record in records.items():
        if key in invalidated:
            continue
        isin = key[0]
        if isin not in candidates or record[:2] > candidates[isin][:2]:
            candidates[isin] = record
    quotes = {}
    for isin, (trade, published, price) in candidates.items():
        prices = {r[2] for k, r in records.items() if k[0] == isin and k not in invalidated and r[0] == trade}
        numeric = float(price)
        if len(prices) != 1 or not math.isfinite(numeric) or numeric <= 0:
            continue
        quotes[isin] = {'isin': isin, 'ticker': INSTRUMENTS[isin], 'price': numeric, 'currency': 'EUR',
                        'trade_timestamp': stamp(trade), 'update_timestamp': stamp(now)}
    return quotes, count

def merge_quotes(previous, incoming):
    merged = dict(previous)
    for isin, quote in incoming.items():
        old = previous.get(isin)
        if old and timestamp(quote['trade_timestamp']) <= timestamp(old['trade_timestamp']):
            continue
        merged[isin] = quote
    return [merged[i] for i in INSTRUMENTS if i in merged]

def update(path, loader=download, now=None):
    now = now or datetime.now(timezone.utc)
    previous = read_previous(path)
    incoming, rows = parse_archive(loader(), now)
    if not incoming:
        raise ValueError('No valid target ETF trades; previous quotes preserved')
    result = merge_quotes(previous, incoming)
    if len(result) != len(INSTRUMENTS):
        raise ValueError('Incomplete first publication; previous quotes preserved')
    content = json.dumps(result, indent=2, allow_nan=False) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as f:
        f.write(content)
        temporary = f.name
    try:
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    missing = sorted(set(INSTRUMENTS) - set(incoming))
    print(f'Processed {rows} CSV rows; published {len(result)} quotes; retained missing ISINs: {missing}')
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('docs/quotes.json'))
    parser.add_argument('--zip', type=Path)
    parser.add_argument('--scheduled-cron', default='')
    parser.add_argument('--gated', action='store_true')
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    if (args.gated or args.scheduled_cron) and not should_run(now):
        print('Skipped: market session in progress, weekend or official Paris closure')
        return
    update(args.output, (lambda: args.zip.read_bytes()) if args.zip else download, now)

if __name__ == '__main__':
    main()
