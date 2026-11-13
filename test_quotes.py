import csv, io, tempfile, unittest, zipfile
from pathlib import Path
from datetime import datetime, timezone
from update_quotes import INSTRUMENTS, REQUIRED, parse_archive, update, should_run, FIELDS
NOW = datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc)

def row(isin='FR0011550185', **changes):
    r = dict.fromkeys(REQUIRED, '-')
    r.update(MifidInstrumentID=isin, MifidPrice='33.81', MifidQuantity='5', MifidCurrency='EUR',
             MifidPriceNotation='MONE', TradingDateTime='2026-11-09T16:35:00Z', PublicationDateTime='2026-11-09T16:35:01Z',
             Venue='XPAR', TradeUniqueIdentifier=isin, MissingPrice='')
    r.update(changes)
    return r

def archive(rows):
    text=io.StringIO(); text.write('(c) Euronext\n')
    w=csv.DictWriter(text,fieldnames=sorted(REQUIRED)); w.writeheader(); w.writerows(rows)
    binary=io.BytesIO()
    with zipfile.ZipFile(binary,'w',zipfile.ZIP_DEFLATED) as z: z.writestr('Trades_ETFSFunds.csv',text.getvalue())
    return binary.getvalue()

class QuoteTests(unittest.TestCase):
    def test_four_isins_and_exact_public_fields(self):
        q,_=parse_archive(archive([row(i) for i in INSTRUMENTS]),NOW)
        self.assertEqual(set(q),set(INSTRUMENTS))
        for isin in q:
            self.assertEqual(set(q[isin]),FIELDS); self.assertEqual(q[isin]['ticker'],INSTRUMENTS[isin])
            self.assertEqual(q[isin]['currency'],'EUR'); self.assertEqual(q[isin]['price'],33.81)
    def test_reject_non_eur(self):
        self.assertEqual(parse_archive(archive([row(MifidCurrency='USD')]),NOW)[0],{})
    def test_cancel_and_correction_remove_original(self):
        for flag in ['CANC','AMND','unknown']:
            with self.subTest(flag=flag):
                self.assertEqual(parse_archive(archive([row(),row(MmtModificationIndicator=flag)]),NOW)[0],{})
    def test_non_price_forming_rejected(self):
        self.assertEqual(parse_archive(archive([row(MmtContributionToPrice='NPFT')]),NOW)[0],{})
    def test_invalid_price_and_quantity(self):
        for field in ['MifidPrice','MifidQuantity']:
            for bad in ['0','-2','NaN','Infinity','bad']:
                with self.subTest(field=field,bad=bad): self.assertEqual(parse_archive(archive([row(**{field:bad})]),NOW)[0],{})
    def test_wrong_venue_and_missing_price(self):
        for changes in [{'Venue':'XAMS'},{'MissingPrice':'MISSING'}]:
            self.assertEqual(parse_archive(archive([row(**changes)]),NOW)[0],{})
    def test_future_timestamp(self):
        self.assertEqual(parse_archive(archive([row(PublicationDateTime='2027-01-01T00:00:00Z')]),NOW)[0],{})
    def test_latest_trade_not_file_order(self):
        q,_=parse_archive(archive([row(TradeUniqueIdentifier='later',MifidPrice='34'),row(TradeUniqueIdentifier='earlier',TradingDateTime='2026-11-09T16:34:00Z')]),NOW)
        self.assertEqual(q['FR0011550185']['price'],34)
    def test_download_failure_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'quotes.json'; update(path,lambda:archive([row(i) for i in INSTRUMENTS]),NOW); before=path.read_bytes()
            def fail(): raise OSError('simulated download failure')
            with self.assertRaises(OSError): update(path,fail,NOW)
            self.assertEqual(path.read_bytes(),before)
    def test_bad_zip_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'quotes.json'; update(path,lambda:archive([row(i) for i in INSTRUMENTS]),NOW); before=path.read_bytes()
            with self.assertRaises(zipfile.BadZipFile): update(path,lambda:b'bad zip',NOW)
            self.assertEqual(path.read_bytes(),before)
    def test_partial_update_keeps_missing_quote(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'q.json'; old=update(p,lambda:archive([row(i) for i in INSTRUMENTS]),NOW)
            result=update(p,lambda:archive([row(MifidPrice='35',TradingDateTime='2026-11-09T16:36:00Z',PublicationDateTime='2026-11-09T16:36:01Z')]),NOW)
            self.assertEqual(result[0]['price'],35); self.assertEqual(result[1:],old[1:])
    def test_stale_download_does_not_advance_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'q.json'; update(p,lambda:archive([row(i) for i in INSTRUMENTS]),NOW); before=p.read_bytes()
            update(p,lambda:archive([row(i) for i in INSTRUMENTS]),datetime(2026,11,10,18,tzinfo=timezone.utc))
            self.assertEqual(p.read_bytes(),before)
    def test_incomplete_first_run_not_published(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'q.json'
            with self.assertRaises(ValueError): update(p,lambda:archive([row()]),NOW)
            self.assertFalse(p.exists())
    def test_after_close_any_delay(self):
        for h in [17,19,22,23]:
            self.assertTrue(should_run(datetime(2026,11,11,h,35,tzinfo=timezone.utc)))
        self.assertTrue(should_run(datetime(2026,7,1,16,30,tzinfo=timezone.utc)))
    def test_late_run_after_midnight_counts_for_previous_session(self):
        self.assertTrue(should_run(datetime(2026,11,11,23,35,tzinfo=timezone.utc)))
        self.assertTrue(should_run(datetime(2026,11,12,5,0,tzinfo=timezone.utc)))
        self.assertFalse(should_run(datetime(2026,11,9,0,30,tzinfo=timezone.utc)))
    def test_never_intraday(self):
        self.assertFalse(should_run(datetime(2026,11,12,11,0,tzinfo=timezone.utc)))
        self.assertFalse(should_run(datetime(2026,7,1,15,30,tzinfo=timezone.utc)))
    def test_weekend_and_verified_closures(self):
        for date in [(2026,11,8),(2026,12,25),(2027,3,26),(2027,3,29)]:
            self.assertFalse(should_run(datetime(*date,18,tzinfo=timezone.utc)))
    def test_half_day_and_french_holiday_market_open(self):
        self.assertTrue(should_run(datetime(2026,12,24,17,30,tzinfo=timezone.utc)))
        self.assertTrue(should_run(datetime(2026,11,11,17,30,tzinfo=timezone.utc)))
    def test_unknown_calendar_year_fails_closed(self):
        with self.assertRaises(ValueError): should_run(datetime(2028,1,3,18,tzinfo=timezone.utc),'30 17 * * *')
    def test_conflicting_same_timestamp_not_guessed(self):
        q,_=parse_archive(archive([row(),row(TradeUniqueIdentifier='other',MifidPrice='34')]),NOW)
        self.assertEqual(q,{})

if __name__=='__main__': unittest.main()
