name: HFT Bot Main
on:
  schedule:
    - cron: '0 */6 * * *'  # Every 6 hours = 24/7
  workflow_dispatch:
  push:
    branches: [main]

jobs:
  bot:
    runs-on: ubuntu-latest
    timeout-minutes: 350  # GitHub max 6h, we use 5h50m
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - name: Install
        run: pip install -r requirements.txt
      - name: Restore Capital
        uses: actions/cache@v4
        with:
          path: |
            capital.json
            memory.json
            ws_ai.pkl
          key: hft-state-${{ github.run_number }}
          restore-keys: hft-state-
      - name: Run HFT Bot
        env:
          MEXC_API_KEY: ${{ secrets.MEXC_API_KEY }}
          MEXC_SECRET: ${{ secrets.MEXC_SECRET }}
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          CHAT_ID: ${{ secrets.CHAT_ID }}
        run: python bot_github.py
      - name: Save State
        uses: actions/cache/save@v4
        if: always()
        with:
          path: |
            capital.json
            memory.json
            ws_ai.pkl
          key: hft-state-${{ github.run_number }}
