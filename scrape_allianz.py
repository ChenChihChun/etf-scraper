#!/usr/bin/env python3
"""
Scrape Allianz Taiwan Active ETF (00993A) holdings using Playwright.
Runs via GitHub Actions, outputs JSON to data/ directory.
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright


ETF_URL = "https://etf.allianzgi.com.tw/etf-info/E0001"
OUTPUT_DIR = Path(__file__).parent / "data"


def scrape_holdings():
    """Scrape 00993A holdings from Allianz website."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()

        # Intercept API responses
        api_data = {}

        def handle_response(response):
            if "GetFundAssets" in response.url:
                try:
                    api_data["assets"] = response.json()
                    print(f"Captured API response: {len(str(api_data['assets']))} bytes")
                except:
                    pass

        page.on("response", handle_response)

        print(f"Loading {ETF_URL}...")
        page.goto(ETF_URL, timeout=60000)
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(2)

        # Click on 資產配置 tab
        print("Looking for 資產配置 tab...")
        try:
            tab_selectors = [
                "text=資產配置",
                "[role='tab']:has-text('資產配置')",
                "a:has-text('資產配置')",
                "button:has-text('資產配置')",
            ]
            for selector in tab_selectors:
                try:
                    tab = page.locator(selector).first
                    if tab.is_visible(timeout=2000):
                        tab.click()
                        print(f"Clicked tab: {selector}")
                        time.sleep(3)
                        break
                except:
                    continue
        except Exception as e:
            print(f"Tab warning: {e}")

        # Take screenshot
        page.screenshot(path=str(OUTPUT_DIR / "debug_screenshot.png"))

        # Try to get data from intercepted API first
        if api_data.get("assets"):
            print("Using intercepted API data")
            holdings_data = parse_api_response(api_data["assets"])
        else:
            print("Parsing from page content")
            holdings_data = parse_page_content(page)

        browser.close()

    return holdings_data


def parse_api_response(api_resp):
    """Parse holdings from intercepted API response."""
    results = {"holdings": [], "meta": {}}

    # Debug: print structure
    print(f"API response type: {type(api_resp)}")
    if isinstance(api_resp, dict):
        print(f"API keys: {list(api_resp.keys())[:10]}")
        entries = api_resp.get("Entries", [])
        if entries and isinstance(entries, list):
            print(f"First entry type: {type(entries[0])}")
            if isinstance(entries[0], dict):
                print(f"First entry keys: {list(entries[0].keys())}")
                print(f"First entry sample: {entries[0]}")

        # Parse based on actual structure
        for entry in entries:
            if not isinstance(entry, dict):
                continue

            # Try different field names
            asset_type = entry.get("AssetType") or entry.get("assetType") or entry.get("Type", "")
            name = entry.get("Name") or entry.get("name") or entry.get("StockName", "")
            code = entry.get("Code") or entry.get("code") or entry.get("StockCode", "")
            weight = entry.get("Weight") or entry.get("weight") or entry.get("NavRate", 0)

            # Include stocks (not cash/futures header rows)
            if name and weight:
                try:
                    w = float(str(weight).replace("%", ""))
                    if 0 < w < 100:
                        results["holdings"].append({
                            "name": str(name),
                            "code": str(code) if code else "",
                            "weight": w,
                        })
                except (ValueError, TypeError):
                    pass

    # Sort by weight
    results["holdings"].sort(key=lambda x: x["weight"], reverse=True)
    return results


def parse_page_content(page):
    """Parse holdings from page HTML."""
    results = page.evaluate("""
        () => {
            const results = {
                holdings: [],
                meta: {},
                debug: { tables: 0 }
            };

            const tables = document.querySelectorAll('table');
            results.debug.tables = tables.length;

            for (const table of tables) {
                const rows = Array.from(table.querySelectorAll('tr'));
                if (rows.length < 2) continue;

                // Find header row to determine column order
                const headerRow = rows[0];
                const headers = Array.from(headerRow.querySelectorAll('th, td'))
                    .map(c => c.innerText.trim().toLowerCase());

                // Look for stock holdings table
                const hasName = headers.some(h => h.includes('名稱') || h.includes('股票'));
                const hasCode = headers.some(h => h.includes('代碼') || h.includes('代號'));
                const hasWeight = headers.some(h => h.includes('比重') || h.includes('權重') || h.includes('%'));

                if (!hasWeight) continue;

                // Determine column indices
                let nameIdx = headers.findIndex(h => h.includes('名稱') || h.includes('股票'));
                let codeIdx = headers.findIndex(h => h.includes('代碼') || h.includes('代號'));
                let weightIdx = headers.findIndex(h => h.includes('比重') || h.includes('權重') || h.includes('%'));

                // If no explicit columns, try positional detection
                if (nameIdx === -1) nameIdx = 0;
                if (weightIdx === -1) weightIdx = headers.length - 1;

                // Parse data rows
                for (let i = 1; i < rows.length; i++) {
                    const cells = Array.from(rows[i].querySelectorAll('td'));
                    if (cells.length < 2) continue;

                    const cellTexts = cells.map(c => c.innerText.trim());

                    // Extract weight (look for number, possibly with %)
                    let weight = 0;
                    for (const txt of cellTexts) {
                        const match = txt.match(/([\\d.]+)\\s*%?$/);
                        if (match && parseFloat(match[1]) > 0 && parseFloat(match[1]) < 100) {
                            weight = parseFloat(match[1]);
                            break;
                        }
                    }
                    if (weight === 0) continue;

                    // Extract code (4 digits)
                    let code = '';
                    for (const txt of cellTexts) {
                        if (/^\\d{4}$/.test(txt)) {
                            code = txt;
                            break;
                        }
                    }

                    // Extract name (non-numeric, non-% text)
                    let name = '';
                    for (const txt of cellTexts) {
                        // Skip if it's the code, weight, or header-like text
                        if (txt === code) continue;
                        if (/^[\\d.]+%?$/.test(txt)) continue;
                        if (txt.includes('名稱') || txt.includes('代碼') || txt.includes('比重')) continue;
                        if (txt.length > 0 && txt.length < 20) {
                            name = txt;
                            break;
                        }
                    }

                    // Special case: futures (TX, MTX, etc.)
                    if (!code && name.match(/^[A-Z]{2,4}$/)) {
                        // It's likely a futures symbol, keep name as-is
                    }

                    if (name || code) {
                        results.holdings.push({ name, code, weight });
                    }
                }
            }

            // Get date
            const dateMatch = document.body.innerText.match(/(\\d{4})[\\/-](\\d{2})[\\/-](\\d{2})/);
            if (dateMatch) {
                results.meta.trade_date = `${dateMatch[1]}-${dateMatch[2]}-${dateMatch[3]}`;
            }

            // Get NAV
            const navMatch = document.body.innerText.match(/淨值[：:]?\\s*([\\d.]+)/);
            if (navMatch) {
                results.meta.nav = parseFloat(navMatch[1]);
            }

            // Deduplicate
            const seen = new Set();
            results.holdings = results.holdings.filter(h => {
                const key = h.code || h.name;
                if (!key || seen.has(key)) return false;
                seen.add(key);
                return true;
            });

            // Sort by weight desc
            results.holdings.sort((a, b) => b.weight - a.weight);

            return results;
        }
    """)

    print(f"Debug: {results.get('debug', {})}")
    print(f"Found {len(results.get('holdings', []))} holdings")

    return results


def save_data(data):
    """Save holdings data to JSON file."""
    today = datetime.now().strftime("%Y-%m-%d")

    output = {
        "etf_code": "00993A",
        "etf_name": "安聯台灣主動式ETF",
        "trade_date": data.get("meta", {}).get("trade_date", today),
        "scraped_at": datetime.now().isoformat(),
        "nav": data.get("meta", {}).get("nav"),
        "holdings": data.get("holdings", []),
        "holdings_count": len(data.get("holdings", []))
    }

    # Save dated file
    filepath = OUTPUT_DIR / f"00993A_{today}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Saved: {filepath}")

    # Save latest
    latest = OUTPUT_DIR / "00993A_latest.json"
    with open(latest, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Saved: {latest}")

    return output


def main():
    print(f"Scraping 00993A at {datetime.now().isoformat()}")

    try:
        data = scrape_holdings()

        if not data.get("holdings"):
            print("WARNING: No holdings found!")
            save_data(data)
            sys.exit(1)

        result = save_data(data)
        print(f"Success: {result['holdings_count']} holdings")

        # Print holdings
        for h in result["holdings"][:10]:
            print(f"  {h['code'] or '----':>4} {h['name']:<12} {h['weight']:.2f}%")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
