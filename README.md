# Euronext Paris ETF quotes

Separate public market-data pipeline. No holdings, quantities, budgets, transactions, account information or Lovable app code is included. Python 3.12 standard library only; no API key, paid data subscription, third-party proxy or paid runner.

## Public JSON

https://shamiherve.github.io/euronext-etf-quotes/quotes.json

Array with exactly six fields per record: isin, ticker, price, currency, trade_timestamp, update_timestamp. UTC ISO timestamps. update_timestamp records successful acceptance of a newer valid trade, not the last attempted download. Unchanged/stale sources do not advance it. Source: Euronext delayed post-trade data, NOT guaranteed official closing prices.

Verified official Paris mappings (append ISIN-XPAR to https://live.euronext.com/en/product/etfs/): FR0011550185 ESE; FR0011550193 ETZ; FR0013411980 PTPXE; FR0013412020 PAEEM.

## Safety

Uses only https://marketdata.euronext.com/data-reporting-service/trades-file with Paris / ETFs & Funds / Since Previous Trading Day. Reads the ZIP's sole CSV without extracting filesystem paths, checks sizes/schema, matches ISIN. Rejects non-XPAR, non-EUR, non-monetary, missing, non-positive/non-finite prices/quantities, malformed/future timestamps, ALL flagged modifications and contributions to price, including NPFT. Unknown flags fail closed: only empty or '-' flags accepted. Modifications tombstone matching original ISIN/venue/trade ID regardless of row order. Ambiguous same-time prices excluded.

No unverified flag dictionary is assumed. Corrections with different trade IDs cannot be reliably linked; cancellation history beyond the source window is unavailable. Preserved quotes may become stale; consumers must show trade timestamps. Corporate-action adjustment and PEA eligibility are not established by this feed.

Validation precedes atomic JSON replacement. Failure leaves the prior file untouched and fails the Actions run. Missing ETFs retain previous quotes; first publication requires all four ETFs. Later/equal-time cached quotes cannot be replaced by stale data. Raw CSV/ZIP files are never published.

## Schedule/calendar

16:30 and 17:30 UTC cron triggers plus Europe/Paris DST gating target 18:30 Paris. Only the seasonally correct trigger downloads. Weekend and official Paris full closures are skipped. Half days still update at 18:30; French public holidays are not assumed exchange closures.

Source: https://www.euronext.com/en/trading/trading-hours-holidays
2026 weekday closures: Jan 1, Apr 3, Apr 6, May 1, Dec 25. Half days Dec 24 and 31.
2027 weekday closures: Jan 1, Mar 26, Mar 29. May 1 and Dec 25/26 are weekends. Half days Dec 24 and 31.
Unknown years fail closed: review the official calendar before 2028. Extraordinary closures require calendar updates; stale/no-trade safeguards still apply.

GitHub scheduling is best effort, may be delayed/dropped, and public schedules may be disabled after 60 days of inactivity. No exact-time guarantee. Manual Actions > Run workflow bypasses time/calendar gates; initial/manual runs may be intraday and are not EOD results.

## Tests and free deployment

python -m unittest -v test_quotes.py
python update_quotes.py

Optional --zip path/to/file.zip for offline fixtures. Daily workflow runs tests. GitHub Pages source must be GitHub Actions. Public standard ubuntu-latest runners and public Pages use the free service under published limits; no private/paid runners, custom domain or paid service. About two short workflow starts/day and four small quote records; quotas/terms may change and traffic/abuse limits apply.

## Attribution and distribution

Source: Euronext. https://www.euronext.com/en/data/pricing-specs-agreements/mifid-ii-compliant-data
Terms: https://www.euronext.com/sites/default/files/stld/terms_and_conditions_for_delayed_data.pdf

Free use is distinct from distribution. Attribute Euronext and prominently show the prescribed disclaimer. Fee-based or commercially beneficial redistribution requires Euronext authorization/agreement. This repository grants no independent data rights. Downstream Lovable displays must carry attribution and full disclaimer, not merely a repository link. Review authorization before integration into paid/commercial services.

> © 2026 Euronext N.V. All Rights Reserved. The information, data, analysis and delayed (pre- and post-)trade data contained herein (i) include the proprietary information of Euronext and its content providers, (ii) may not be copied or further disseminated, by any media whatsoever, except as specifically authorized by Euronext, (iii) do not constitute investment advice, (iv) are provided solely for informational purposes and (v) are not warranted to be complete, accurate or timely.

JSON contains only the six requested fields; the accompanying page prominently displays the disclaimer.
