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

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


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

        print(f"Loading {ETF_URL}...")
        page.goto(ETF_URL, timeout=60000)

        # Wait for Angular app to load
        print("Waiting for page to load...")
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(3)  # Extra wait for Angular rendering

        # Click on "資產配置" tab (tab index 4)
        print("Looking for 資產配置 tab...")
        try:
            # Try multiple selectors for the tab
            tab_selectors = [
                "text=資產配置",
                "[role='tab']:has-text('資產配置')",
                ".nav-link:has-text('資產配置')",
                "a:has-text('資產配置')",
                "button:has-text('資產配置')",
            ]

            tab_clicked = False
            for selector in tab_selectors:
                try:
                    tab = page.locator(selector).first
                    if tab.is_visible(timeout=2000):
                        tab.click()
                        tab_clicked = True
                        print(f"Clicked tab using: {selector}")
                        break
                except:
                    continue

            if not tab_clicked:
                print("Could not find tab, trying direct URL...")
                page.goto(f"{ETF_URL}?tab=4", timeout=30000)
                page.wait_for_load_state("networkidle", timeout=30000)

        except Exception as e:
            print(f"Tab click warning: {e}")

        # Wait for content to load
        time.sleep(3)

        # Take screenshot for debugging
        page.screenshot(path=str(OUTPUT_DIR / "debug_screenshot.png"))
        print("Saved debug screenshot")

        # Get page content for analysis
        page_text = page.inner_text("body")
        print(f"Page text length: {len(page_text)}")

        # Extract holdings data
        holdings_data = page.evaluate("""
            () => {
                const results = {
                    holdings: [],
                    meta: {},
                    debug: {
                        tables: 0,
                        pageTitle: document.title,
                        bodyLength: document.body.innerText.length
                    }
                };

                // Find all tables
                const tables = document.querySelectorAll('table');
                results.debug.tables = tables.length;

                // Look for holdings data in various formats
                for (const table of tables) {
                    const tableText = table.innerText.toLowerCase();

                    // Check if this table has stock-related content
                    if (tableText.includes('台積電') || tableText.includes('tsmc') ||
                        tableText.includes('2330') || tableText.includes('股票') ||
                        tableText.includes('比重') || tableText.includes('%')) {

                        const rows = table.querySelectorAll('tr');
                        rows.forEach((row, idx) => {
                            const cells = row.querySelectorAll('td, th');
                            if (cells.length >= 2) {
                                // Try to extract stock info
                                const rowText = Array.from(cells).map(c => c.innerText.trim());

                                // Look for patterns like "股票名稱 | 代碼 | 比重%"
                                let name = '';
                                let code = '';
                                let weight = 0;

                                for (let i = 0; i < rowText.length; i++) {
                                    const cell = rowText[i];

                                    // Check for stock code (4 digits)
                                    if (/^\\d{4}$/.test(cell)) {
                                        code = cell;
                                    }
                                    // Check for weight (number with %)
                                    else if (/%/.test(cell) || /^\\d+\\.\\d+$/.test(cell)) {
                                        weight = parseFloat(cell.replace('%', ''));
                                    }
                                    // Otherwise might be name
                                    else if (cell.length > 1 && !cell.includes('股票') &&
                                             !cell.includes('名稱') && !cell.includes('比重')) {
                                        if (!name) name = cell;
                                    }
                                }

                                if ((name || code) && weight > 0) {
                                    results.holdings.push({ name, code, weight });
                                }
                            }
                        });
                    }
                }

                // Also try to find JSON data in scripts
                const scripts = document.querySelectorAll('script');
                scripts.forEach(script => {
                    const text = script.innerText;
                    if (text.includes('holdings') || text.includes('assets')) {
                        try {
                            // Look for JSON arrays
                            const matches = text.match(/\\[\\{[^\\[\\]]+\\}\\]/g);
                            if (matches) {
                                matches.forEach(m => {
                                    try {
                                        const data = JSON.parse(m);
                                        if (Array.isArray(data) && data.length > 0 && data[0].weight) {
                                            results.holdings = results.holdings.concat(data);
                                        }
                                    } catch {}
                                });
                            }
                        } catch {}
                    }
                });

                // Get date from page
                const dateMatch = document.body.innerText.match(/(\\d{4})[\\/-](\\d{2})[\\/-](\\d{2})/);
                if (dateMatch) {
                    results.meta.trade_date = `${dateMatch[1]}-${dateMatch[2]}-${dateMatch[3]}`;
                }

                // Try to find NAV
                const navMatch = document.body.innerText.match(/淨值[：:]*\\s*([\\d.]+)/);
                if (navMatch) {
                    results.meta.nav = parseFloat(navMatch[1]);
                }

                // Deduplicate holdings
                const seen = new Set();
                results.holdings = results.holdings.filter(h => {
                    const key = h.code || h.name;
                    if (seen.has(key)) return false;
                    seen.add(key);
                    return true;
                });

                return results;
            }
        """)

        print(f"Debug info: {holdings_data.get('debug', {})}")
        print(f"Found {len(holdings_data.get('holdings', []))} holdings")

        # If no holdings found, save page source for debugging
        if not holdings_data.get("holdings"):
            html_path = OUTPUT_DIR / "debug_page.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(page.content())
            print(f"Saved page HTML to {html_path}")

        browser.close()

    return holdings_data


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

    # Save to dated file
    filename = f"00993A_{today}.json"
    filepath = OUTPUT_DIR / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Saved to {filepath}")

    # Also save as latest
    latest_path = OUTPUT_DIR / "00993A_latest.json"
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Saved to {latest_path}")

    return output


def main():
    print(f"Scraping 00993A holdings at {datetime.now().isoformat()}")

    try:
        data = scrape_holdings()

        if not data.get("holdings"):
            print("WARNING: No holdings data found!")
            print("Check debug_screenshot.png and debug_page.html for details")
            # Save empty result for debugging
            save_data(data)
            sys.exit(1)

        result = save_data(data)
        print(f"Successfully scraped {result['holdings_count']} holdings")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
