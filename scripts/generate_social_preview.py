#!/usr/bin/env python3
"""
Generate a branded GitHub social preview image for arXiv Digest.

Requires Playwright with Chromium installed:
  python3 -m playwright install chromium
"""

from __future__ import annotations

import asyncio
import html
from pathlib import Path
import sys

from playwright.async_api import async_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from brand import ASH_BLACK, ASH_WHITE, CARD_BORDER, FONT_BODY, FONT_HEADING, FONT_MONO, GOLD, PINE, PINE_LIGHT, PINE_WASH, WARM_GREY


OUTPUT_PATH = REPO_ROOT / ".github" / "social-preview.png"


HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap');

    :root {{
      --ash-white: {ASH_WHITE};
      --ash-black: {ASH_BLACK};
      --pine: {PINE};
      --pine-light: {PINE_LIGHT};
      --pine-wash: {PINE_WASH};
      --gold: {GOLD};
      --warm-grey: {WARM_GREY};
      --border: {CARD_BORDER};
      --font-heading: {FONT_HEADING};
      --font-body: {FONT_BODY};
      --font-mono: {FONT_MONO};
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    body {{
      width: 1280px;
      height: 640px;
      overflow: hidden;
      font-family: var(--font-body);
      background:
        radial-gradient(circle at 82% 18%, rgba(235, 201, 68, 0.28), transparent 18%),
        radial-gradient(circle at 68% 72%, rgba(235, 201, 68, 0.14), transparent 28%),
        linear-gradient(135deg, #1e3327 0%, var(--pine) 42%, #13231a 100%);
      color: var(--ash-white);
    }}

    .canvas {{
      position: relative;
      width: 100%;
      height: 100%;
      padding: 56px 64px;
      isolation: isolate;
    }}

    .canvas::before {{
      content: "";
      position: absolute;
      inset: 0;
      background-image:
        linear-gradient(rgba(246, 245, 242, 0.07) 1px, transparent 1px),
        linear-gradient(90deg, rgba(246, 245, 242, 0.07) 1px, transparent 1px);
      background-size: 64px 64px;
      opacity: 0.18;
      z-index: -3;
    }}

    .canvas::after {{
      content: "";
      position: absolute;
      right: -120px;
      top: -120px;
      width: 480px;
      height: 480px;
      border-radius: 50%;
      border: 1px solid rgba(246, 245, 242, 0.18);
      box-shadow:
        0 0 0 72px rgba(246, 245, 242, 0.04),
        0 0 0 144px rgba(246, 245, 242, 0.03);
      z-index: -2;
    }}

    .spark {{
      position: absolute;
      color: rgba(235, 201, 68, 0.85);
      font-size: 18px;
      line-height: 1;
    }}

    .spark.s1 {{ top: 84px; right: 212px; }}
    .spark.s2 {{ top: 204px; right: 108px; font-size: 12px; }}
    .spark.s3 {{ bottom: 106px; right: 166px; font-size: 14px; }}

    .header {{
      display: flex;
      align-items: center;
      gap: 16px;
      margin-bottom: 42px;
    }}

    .mark {{
      width: 42px;
      height: 42px;
      border-radius: 50%;
      border: 1px solid rgba(246, 245, 242, 0.18);
      background:
        radial-gradient(circle at 34% 34%, rgba(235, 201, 68, 0.95), transparent 18%),
        radial-gradient(circle at 68% 64%, rgba(235, 201, 68, 0.45), transparent 34%),
        linear-gradient(135deg, rgba(246, 245, 242, 0.1), rgba(246, 245, 242, 0.03));
      box-shadow: 0 0 30px rgba(235, 201, 68, 0.12);
    }}

    .kicker {{
      font-family: var(--font-mono);
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-size: 14px;
      color: rgba(246, 245, 242, 0.72);
    }}

    .layout {{
      display: grid;
      grid-template-columns: 1.3fr 0.92fr;
      gap: 36px;
      align-items: end;
      height: calc(100% - 110px);
    }}

    .title {{
      max-width: 680px;
      font-family: var(--font-heading);
      font-size: 96px;
      line-height: 0.92;
      letter-spacing: -0.04em;
      margin-bottom: 24px;
    }}

    .title em {{
      font-style: italic;
      color: var(--gold);
    }}

    .lede {{
      max-width: 560px;
      font-size: 28px;
      line-height: 1.36;
      font-weight: 300;
      color: rgba(246, 245, 242, 0.92);
      margin-bottom: 34px;
    }}

    .pills {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
    }}

    .pill {{
      border: 1px solid rgba(246, 245, 242, 0.18);
      background: rgba(246, 245, 242, 0.07);
      backdrop-filter: blur(12px);
      border-radius: 999px;
      padding: 10px 16px;
      font-family: var(--font-mono);
      font-size: 14px;
      letter-spacing: 0.04em;
      color: rgba(246, 245, 242, 0.88);
    }}

    .card {{
      align-self: center;
      justify-self: stretch;
      display: flex;
      flex-direction: column;
      background: rgba(246, 245, 242, 0.96);
      color: var(--ash-black);
      border: 1px solid rgba(246, 245, 242, 0.6);
      border-radius: 28px;
      padding: 26px 28px 24px;
      box-shadow:
        0 30px 60px rgba(0, 0, 0, 0.22),
        0 0 0 1px rgba(47, 79, 62, 0.06);
      min-height: 412px;
      position: relative;
      overflow: hidden;
    }}

    .card::before {{
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      top: 0;
      height: 9px;
      background: linear-gradient(90deg, var(--gold) 0%, #f2dc7f 100%);
    }}

    .card-label {{
      font-family: var(--font-mono);
      font-size: 13px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--warm-grey);
      margin-bottom: 18px;
    }}

    .paper-title {{
      font-family: var(--font-heading);
      font-size: 43px;
      line-height: 0.96;
      letter-spacing: -0.03em;
      margin-bottom: 18px;
      color: var(--pine);
    }}

    .paper-title em {{
      font-style: italic;
      color: #96733a;
    }}

    .paper-body {{
      font-size: 20px;
      line-height: 1.42;
      color: #40403d;
      margin-bottom: 28px;
      max-width: 420px;
    }}

    .rule {{
      height: 1px;
      background: linear-gradient(90deg, rgba(47, 79, 62, 0.2), rgba(47, 79, 62, 0.02));
      margin-bottom: 22px;
    }}

    .score-row {{
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 14px 18px;
      align-items: center;
      margin-bottom: 18px;
    }}

    .score-label {{
      font-family: var(--font-mono);
      font-size: 13px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--warm-grey);
    }}

    .bar {{
      display: grid;
      grid-template-columns: repeat(10, 1fr);
      gap: 6px;
    }}

    .dot {{
      height: 10px;
      border-radius: 999px;
      background: #d8d6d0;
    }}

    .dot.on {{
      background: linear-gradient(90deg, var(--gold), #f2dc7f);
    }}

    .meta {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 8px;
      margin-bottom: 18px;
    }}

    .meta-chip {{
      background: {PINE_WASH};
      border: 1px solid {CARD_BORDER};
      border-radius: 999px;
      color: var(--pine);
      font-size: 14px;
      padding: 8px 12px;
    }}

    .footer {{
      margin-top: auto;
      padding-top: 16px;
      border-top: 1px solid rgba(47, 79, 62, 0.14);
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px 16px;
      align-items: end;
      font-family: var(--font-mono);
      font-size: 12px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--warm-grey);
    }}

    .footer strong {{
      color: var(--pine);
      font-weight: 500;
    }}

    .footer-right {{
      text-align: right;
      color: var(--pine);
    }}
  </style>
</head>
<body>
  <main class="canvas">
    <div class="spark s1">✦</div>
    <div class="spark s2">✦</div>
    <div class="spark s3">✦</div>

    <header class="header">
      <div class="mark"></div>
      <div class="kicker">Personal arXiv curator for astronomers</div>
    </header>

    <section class="layout">
      <div>
        <h1 class="title">arXiv <em>Digest</em></h1>
        <p class="lede">
          AI-powered paper scoring, curated highlights, and a clean email digest
          that keeps new astronomy work in reach without the morning tab spiral.
        </p>
        <div class="pills">
          <div class="pill">Invite-only easy setup</div>
          <div class="pill">Inbox delivery</div>
          <div class="pill">GitHub Actions</div>
        </div>
      </div>

      <aside class="card">
        <div class="card-label">Sample digest card</div>
        <h2 class="paper-title">Targeted picks, not <em>noise</em></h2>
        <p class="paper-body">
          Match new papers against your keywords, research context, favorite
          authors, and field-specific categories before they hit your inbox.
        </p>
        <div class="rule"></div>
        <div class="score-row">
          <div class="score-label">Relevance</div>
          <div class="bar">
            <div class="dot on"></div>
            <div class="dot on"></div>
            <div class="dot on"></div>
            <div class="dot on"></div>
            <div class="dot on"></div>
            <div class="dot on"></div>
            <div class="dot on"></div>
            <div class="dot on"></div>
            <div class="dot"></div>
            <div class="dot"></div>
          </div>
        </div>
        <div class="meta">
          <div class="meta-chip">astro-ph.GA</div>
          <div class="meta-chip">JWST</div>
          <div class="meta-chip">Exoplanets</div>
        </div>
        <div class="footer">
          <div>Created by <strong>Silke S. Dainese</strong></div>
          <div class="footer-right">SilkeDainese/arxiv-digest</div>
        </div>
      </aside>
    </section>
  </main>
</body>
</html>
"""


async def render_social_preview() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 640}, device_scale_factor=1)
        await page.set_content(HTML, wait_until="networkidle")
        await page.locator(".canvas").screenshot(path=str(OUTPUT_PATH))
        await browser.close()


def main() -> None:
    asyncio.run(render_social_preview())
    print(html.escape(str(OUTPUT_PATH)))


if __name__ == "__main__":
    main()
