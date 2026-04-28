#!/usr/bin/env python3
"""
Scrape 00993A full holdings from pocket.tw using Playwright.
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright


ETF_URL = "https://www.pocket.tw/etf/tw/00993A/fundholding"
OUTPUT_DIR = Path(__file__).parent / "data"


def scrape_holdings():
    """Scrape 00993A holdings from pocket.tw."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()

        print(f"Loading {ETF_URL}...")
        page.goto(ETF_URL, timeout=60000)
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(3)

        # Take screenshot
        page.screenshot(path=str(OUTPUT_DIR / "debug_pocket.png"))
        print("Screenshot saved")

        # Extract holdings from table
        holdings_data = page.evaluate("""
            () => {
                const results = {
                    holdings: [],
                    meta: {},
                    debug: { tables: 0 }
                };

                // Find all tables
                const tables = document.querySelectorAll('table');
                results.debug.tables = tables.length;
                console.log('Found tables:', tables.length);

                for (const table of tables) {
                    const rows = Array.from(table.querySelectorAll('tr'));
                    if (rows.length < 2) continue;

                    // Check headers
                    const headerRow = rows[0];
                    const headers = Array.from(headerRow.querySelectorAll('th, td'))
                        .map(c => c.innerText.trim().toLowerCase());

                    console.log('Headers:', headers);

                    // Look for holdings table (has 股票/名稱 and 比重/權重)
                    const hasStockCol = headers.some(h =>
                        h.includes('股票') || h.includes('名稱') || h.includes('證券'));
                    const hasWeightCol = headers.some(h =>
                        h.includes('比重') || h.includes('權重') || h.includes('佔比') || h.includes('%'));

                    if (!hasStockCol || !hasWeightCol) continue;

                    console.log('Found holdings table');

                    // Find column indices
                    let codeIdx = headers.findIndex(h => h.includes('代碼') || h.includes('代號'));
                    let nameIdx = headers.findIndex(h => h.includes('名稱') || h.includes('股票'));
                    let weightIdx = headers.findIndex(h =>
                        h.includes('比重') || h.includes('權重') || h.includes('佔比'));

                    // Parse data rows
                    for (let i = 1; i < rows.length; i++) {
                        const cells = Array.from(rows[i].querySelectorAll('td'));
                        if (cells.length < 2) continue;

                        const cellTexts = cells.map(c => c.innerText.trim());

                        // Extract code (4-6 digits, or futures code like 202605TX)
                        let code = '';
                        for (const txt of cellTexts) {
                            if (/^\\d{4,6}$/.test(txt) || /^\\d{6}[A-Z]{2}$/.test(txt)) {
                                code = txt;
                                break;
                            }
                        }

                        // Extract weight (decimal with %)
                        let weight = 0;
                        for (const txt of cellTexts) {
                            if (txt.includes('%')) {
                                const match = txt.match(/([\\d.]+)\\s*%/);
                                if (match) {
                                    weight = parseFloat(match[1]);
                                    break;
                                }
                            }
                        }

                        // Extract shares (large number, possibly with commas)
                        let shares = 0;
                        for (const txt of cellTexts) {
                            // Look for numbers like "7,318,000" or "469,000"
                            const cleanNum = txt.replace(/,/g, '');
                            if (/^\\d+$/.test(cleanNum)) {
                                const val = parseInt(cleanNum);
                                // Shares are typically large numbers (> 1000 for stocks)
                                // but could be small for futures (口)
                                if (val >= 1) {
                                    shares = val;
                                }
                            }
                        }

                        // Extract name (Chinese text, not number)
                        let name = '';
                        for (const txt of cellTexts) {
                            if (txt === code) continue;
                            if (/^[\\d.%,]+$/.test(txt)) continue;
                            if (txt === '股' || txt === '口') continue;
                            if (txt.length >= 2 && txt.length <= 20 && /[\\u4e00-\\u9fff]/.test(txt)) {
                                name = txt;
                                break;
                            }
                        }

                        if ((name || code) && weight > 0) {
                            results.holdings.push({ name, code, weight, shares });
                        }
                    }
                }

                // Also try to find data in divs/lists (some sites use cards not tables)
                if (results.holdings.length === 0) {
                    const cards = document.querySelectorAll('[class*="holding"], [class*="stock"], [class*="asset"]');
                    console.log('Trying card elements:', cards.length);
                }

                // Get date from page
                const dateMatch = document.body.innerText.match(/(\\d{4})[\\/-](\\d{2})[\\/-](\\d{2})/);
                if (dateMatch) {
                    results.meta.trade_date = `${dateMatch[1]}-${dateMatch[2]}-${dateMatch[3]}`;
                }

                // Sort by weight desc
                results.holdings.sort((a, b) => b.weight - a.weight);

                return results;
            }
        """)

        print(f"Debug: {holdings_data.get('debug', {})}")
        print(f"Found {len(holdings_data.get('holdings', []))} holdings")

        # If no holdings, save page HTML for debugging
        if not holdings_data.get("holdings"):
            html_path = OUTPUT_DIR / "debug_pocket.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(page.content())
            print(f"Saved HTML to {html_path}")

        browser.close()

    return holdings_data


def save_data(data):
    """Save holdings data to JSON file."""
    today = datetime.now().strftime("%Y-%m-%d")

    output = {
        "etf_code": "00993A",
        "etf_name": "安聯台灣主動式ETF",
        "source": "pocket.tw",
        "trade_date": data.get("meta", {}).get("trade_date", today),
        "scraped_at": datetime.now().isoformat(),
        "holdings": data.get("holdings", []),
        "holdings_count": len(data.get("holdings", []))
    }

    # Calculate total weight
    total_weight = sum(h["weight"] for h in output["holdings"])
    output["total_weight"] = round(total_weight, 2)

    # Save
    filepath = OUTPUT_DIR / f"00993A_{today}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Saved: {filepath}")

    latest = OUTPUT_DIR / "00993A_latest.json"
    with open(latest, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Saved: {latest}")

    return output


def main():
    print(f"Scraping 00993A from pocket.tw at {datetime.now().isoformat()}")

    try:
        data = scrape_holdings()

        if not data.get("holdings"):
            print("WARNING: No holdings found!")
            save_data(data)
            sys.exit(1)

        result = save_data(data)
        print(f"Success: {result['holdings_count']} holdings, total weight: {result['total_weight']}%")

        for h in result["holdings"][:10]:
            print(f"  {h['code']:>6} {h['name']:<12} {h['weight']:.2f}%")
        if result['holdings_count'] > 10:
            print(f"  ... and {result['holdings_count'] - 10} more")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
