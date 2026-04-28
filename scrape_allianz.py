#!/usr/bin/env python3
"""
Scrape Allianz Taiwan Active ETF (00993A) holdings using Playwright.
Runs via GitHub Actions, outputs JSON to data/ directory.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright


ETF_URL = "https://etf.allianzgi.com.tw/etf-info/E0001?tab=4"
OUTPUT_DIR = Path(__file__).parent / "data"


def scrape_holdings():
    """Scrape 00993A holdings from Allianz website."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print(f"Loading {ETF_URL}...")
        page.goto(ETF_URL, wait_until="networkidle", timeout=60000)

        # Wait for holdings table to load
        page.wait_for_selector("table", timeout=30000)

        # Extract holdings data from the page
        # The holdings tab (tab=4) shows stock holdings
        holdings_data = page.evaluate("""
            () => {
                const results = {
                    holdings: [],
                    meta: {}
                };

                // Find all tables on the page
                const tables = document.querySelectorAll('table');

                for (const table of tables) {
                    const rows = table.querySelectorAll('tr');
                    const headers = [];

                    // Get headers
                    const headerRow = table.querySelector('tr');
                    if (headerRow) {
                        headerRow.querySelectorAll('th, td').forEach(cell => {
                            headers.push(cell.innerText.trim());
                        });
                    }

                    // Check if this looks like a holdings table
                    const headerText = headers.join(' ').toLowerCase();
                    if (headerText.includes('股票') || headerText.includes('stock') ||
                        headerText.includes('比重') || headerText.includes('weight')) {

                        // Parse data rows
                        rows.forEach((row, idx) => {
                            if (idx === 0) return; // Skip header
                            const cells = row.querySelectorAll('td');
                            if (cells.length >= 3) {
                                const holding = {
                                    name: cells[0]?.innerText?.trim() || '',
                                    code: cells[1]?.innerText?.trim() || '',
                                    weight: parseFloat(cells[2]?.innerText?.replace('%', '').trim()) || 0
                                };
                                if (holding.name && holding.weight > 0) {
                                    results.holdings.push(holding);
                                }
                            }
                        });
                    }
                }

                // Try to get NAV and date info
                const navElements = document.querySelectorAll('[class*="nav"], [class*="Nav"]');
                navElements.forEach(el => {
                    const text = el.innerText;
                    if (text.includes('淨值') || text.includes('NAV')) {
                        const match = text.match(/[\d.]+/);
                        if (match) {
                            results.meta.nav = parseFloat(match[0]);
                        }
                    }
                });

                // Get date
                const dateMatch = document.body.innerText.match(/(\d{4})[\/\-](\d{2})[\/\-](\d{2})/);
                if (dateMatch) {
                    results.meta.trade_date = `${dateMatch[1]}-${dateMatch[2]}-${dateMatch[3]}`;
                }

                return results;
            }
        """)

        browser.close()

    return holdings_data


def save_data(data):
    """Save holdings data to JSON file."""
    today = datetime.now().strftime("%Y-%m-%d")

    # Add metadata
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
            # Try alternative parsing or exit with error
            sys.exit(1)

        result = save_data(data)
        print(f"Successfully scraped {result['holdings_count']} holdings")

    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
