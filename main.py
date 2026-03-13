#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import logging
import random
import re
import string
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

import pytz
from fake_useragent import UserAgent
import requests
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from temp_gmail import GMail
import stem
from stem.control import Controller

# ================== KONFIGURATSIYA ==================
NUM_ACCOUNTS = 110
CODE_TIMEOUT = 120
TOR_PROXY = "socks5://127.0.0.1:9050"
TOR_CONTROL_PORT = 9051          # control port (cookie auth)
TOKENS_FILE = "tokens.json"
LOG_FILE = "bot.log"
HEADLESS = False                  # headful tavsiya (fingerprint uchun)
PAGE_TIMEOUT = 60000

SIGNUP_URL = "https://digen.ai/signup"
IMAGE_URL = "https://digen.ai/image"

# ================== LOGNI SOZLASH ==================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ================== TOR IDENTIFIKATORINI YANGILASH ==================
async def renew_tor_identity():
    """Tor control port orqali NEWNYM yuboradi (cookie authentication)"""
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _renew_tor_sync)
        log.info("🔄 Tor identifikatori yangilandi")
        await asyncio.sleep(5)   # yangi sxema o'rnatilishi uchun kutish
    except Exception as e:
        log.warning(f"Tor yangilashda xato: {e}")

def _renew_tor_sync():
    with Controller.from_port(port=TOR_CONTROL_PORT) as controller:
        # CookieAuthentication=1 bo'lsa, authenticate() avtomatik cookie faylini o'qiydi
        controller.authenticate()
        controller.signal(stem.Signal.NEWNYM)

# ================== FINGERPRINT GENERATORI ==================
ua = UserAgent()

WEBGL_VENDORS = [
    "Google Inc. (Intel)", "Google Inc. (NVIDIA)", "Google Inc. (AMD)",
    "Intel Inc.", "NVIDIA Corporation", "AMD", "Apple", "Qualcomm"
]
WEBGL_RENDERERS = [
    "ANGLE (Intel, Intel(R) UHD Graphics 620 (0x00005917) Direct3D11 vs_5_0 ps_5_0)",
    "ANGLE (NVIDIA, NVIDIA GeForce GTX 1050 Ti Direct3D11 vs_5_0 ps_5_0)",
    "ANGLE (AMD, Radeon RX 580 Series Direct3D11 vs_5_0 ps_5_0)",
    "Intel Iris OpenGL Engine", "Apple M1", "Adreno (TM) 650", "Mali-G72"
]

WINDOWS_FONTS = ["Arial", "Verdana", "Tahoma", "Segoe UI", "Calibri", "Times New Roman", "Courier New"]
MAC_FONTS = ["Helvetica", "Arial", "Times", "Courier", "Verdana", "Georgia", "Palatino"]
LINUX_FONTS = ["DejaVu Sans", "Liberation Sans", "FreeSans", "Ubuntu", "Noto Sans"]

AUDIO_SAMPLE_RATES = [44100, 48000, 96000]
AUDIO_CHANNELS = [1, 2]

def random_fingerprint() -> Dict:
    timezone = random.choice(pytz.all_timezones)
    locales = [
        "uz-UZ", "ru-RU", "en-US", "en-GB", "es-ES", "fr-FR", "de-DE",
        "it-IT", "pt-BR", "tr-TR", "ar-SA", "hi-IN", "zh-CN", "ja-JP",
        "ko-KR", "nl-NL", "sv-SE", "da-DK", "fi-FI", "no-NO", "pl-PL",
        "cs-CZ", "hu-HU", "ro-RO", "bg-BG", "el-GR", "he-IL", "th-TH",
        "vi-VN", "id-ID", "ms-MY", "fil-PH", "hr-HR", "sk-SK", "sl-SI",
        "et-EE", "lv-LV", "lt-LT", "uk-UA", "sr-RS", "mk-MK", "sq-AL",
        "bg-BG", "ro-RO", "hu-HU", "pl-PL", "cs-CZ", "sk-SK"
    ]
    locale = random.choice(locales)

    platforms = [
        "Win32", "MacIntel", "Linux x86_64", "iPhone", "Android",
        "Windows", "Macintosh", "X11; Linux x86_64", "iPad", "iPod"
    ]
    platform = random.choice(platforms)

    viewports = [
        (1280, 720), (1366, 768), (1920, 1080), (1536, 864),
        (1440, 900), (1600, 900), (1024, 768), (375, 667), (414, 736),
        (390, 844), (393, 873), (412, 915), (360, 800), (768, 1024),
        (1280, 800), (1440, 960), (2560, 1440), (2560, 1600), (2048, 1536),
        (2732, 2048), (1136, 640), (1334, 750), (2208, 1242), (2688, 1242)
    ]
    viewport = random.choice(viewports)

    hw_concurrency = random.choice([2, 4, 6, 8, 12, 16])
    device_memory = random.choice([2, 4, 8, 16])
    color_depth = random.choice([24, 30, 48])
    pixel_ratio = random.choice([1, 2, 3])
    max_touch_points = random.choice([0, 1, 5, 10])

    # Fontlar
    if "Win" in platform:
        font_families = WINDOWS_FONTS
    elif "Mac" in platform or "iPhone" in platform or "iPad" in platform:
        font_families = MAC_FONTS
    else:
        font_families = LINUX_FONTS
    k = min(random.randint(5, 10), len(font_families))
    fonts = random.sample(font_families, k)

    return {
        "user_agent": ua.random,
        "viewport": {"width": viewport[0], "height": viewport[1]},
        "timezone_id": timezone,
        "locale": locale,
        "platform": platform,
        "color_depth": color_depth,
        "device_scale_factor": pixel_ratio,
        "hardware_concurrency": hw_concurrency,
        "device_memory": device_memory,
        "max_touch_points": max_touch_points,
        "webgl_vendor": random.choice(WEBGL_VENDORS),
        "webgl_renderer": random.choice(WEBGL_RENDERERS),
        "fonts": fonts,
        "audio_sample_rate": random.choice(AUDIO_SAMPLE_RATES),
        "audio_channels": random.choice(AUDIO_CHANNELS),
    }

# ================== KUCHLI PAROL GENERATORI ==================
def gen_password() -> str:
    chars = (
        random.choices(string.ascii_uppercase, k=3) +
        random.choices(string.ascii_lowercase, k=5) +
        random.choices(string.digits, k=3) +
        random.choices("@#$%^&*", k=2)
    )
    random.shuffle(chars)
    return "".join(chars)

# ================== KODNI KUTISH ==================
async def wait_for_code(gmail: GMail, timeout: int = 180) -> str:
    log.info("⏳ Kod kutilmoqda...")
    start = time.time()
    seen_ids = set()

    while time.time() - start < timeout:
        try:
            raw = await asyncio.to_thread(gmail.load_list)
            message_list = []
            if isinstance(raw, dict):
                message_list = raw.get("messageData", [])
            elif isinstance(raw, list):
                message_list = raw

            for msg in message_list:
                sender = msg.get("from", "").lower()
                subject = msg.get("subject", "").lower()
                if "digen" in sender or "digen" in subject or "verify" in subject:
                    msg_id = msg.get("messageID") or msg.get("messageId")
                    if msg_id and msg_id not in seen_ids:
                        seen_ids.add(msg_id)
                        # Subject dan kod
                        m = re.search(r"\b(\d{6})\b", subject)
                        if m:
                            log.info(f"🔑 Kod (subject): {m.group(1)}")
                            return m.group(1)
                        # Body dan kod
                        body = str(await asyncio.to_thread(gmail.load_item, msg_id))
                        m = re.search(r"\b(\d{6})\b", body)
                        if m:
                            log.info(f"🔑 Kod (body): {m.group(1)}")
                            return m.group(1)
            await asyncio.sleep(random.uniform(4, 8))
        except Exception as e:
            log.warning(f"Inbox xatosi: {e}")
            await asyncio.sleep(random.uniform(4, 8))

    raise TimeoutError(f"Kod {timeout}s da kelmadi")

# ================== VERIFY TUGMASINI BOSISH ==================
async def verify_until_password_appears(page, max_attempts: int = 5):
    for attempt in range(1, max_attempts + 1):
        verify_btn = await page.query_selector("button.relative")
        if verify_btn:
            await verify_btn.click()
            log.info(f"🖱️ Verify tugmasi bosildi (urinish {attempt})")
        else:
            log.warning(f"Verify tugmasi topilmadi (urinish {attempt})")
            continue

        try:
            await page.wait_for_selector("#form_item_password", state="visible", timeout=20000)
            log.info("✅ Parol formasi paydo bo'ldi")
            return True
        except PlaywrightTimeout:
            log.info("⏳ Parol formasi hali yo'q, qayta urinish...")
            continue

    raise Exception(f"❌ Parol formasi {max_attempts} urinishda ham topilmadi")

# ================== BITTA AKKAUNT YARATISH ==================
async def create_account(proxy: Optional[str]) -> dict:
    # Har bir akkaunt oldidan Tor identifikatorini yangilaymiz
    await renew_tor_identity()

    fp = random_fingerprint()
    log.info(f"📍 Fingerprint: {fp['timezone_id']} / {fp['locale']} / {fp['platform']}")

    # Email yaratish
    gmail = await asyncio.to_thread(GMail)
    email = await asyncio.to_thread(gmail.create_email)
    password = gen_password()
    log.info(f"📧 Email: {email}")
    log.info(f"🔑 Parol: {password}")

    digen_token = None
    digen_sessionid = None

    async with async_playwright() as pw:
        launch_opts = {
            "headless": HEADLESS,
            "proxy": {"server": proxy} if proxy else None,
            "args": [
                f"--window-size={fp['viewport']['width']},{fp['viewport']['height']}",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        }
        browser = await pw.chromium.launch(**launch_opts)
        context = await browser.new_context(
            viewport=fp['viewport'],
            user_agent=fp['user_agent'],
            locale=fp['locale'],
            timezone_id=fp['timezone_id'],
            color_scheme=random.choice(["light", "dark"]),
            reduced_motion=random.choice(["reduce", "no-preference"]),
            extra_http_headers={
                "Accept-Language": fp['locale'].replace("_", "-"),
            },
            device_scale_factor=fp['device_scale_factor'],
            has_touch=random.choice([True, False]),
        )

        # Stealth JS (brauzer izlarini yashirish)
        stealth_js = f"""
        // WebGL vendor/renderer
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {{
            if (parameter === 37445) {{
                return '{fp['webgl_vendor']}';
            }}
            if (parameter === 37446) {{
                return '{fp['webgl_renderer']}';
            }}
            return getParameter(parameter);
        }};

        // Canvas fingerprinting (random noise)
        const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type, encoderOptions) {{
            if (type === 'image/png' || type === 'image/jpeg') {{
                const canvas = document.createElement('canvas');
                canvas.width = this.width;
                canvas.height = this.height;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(this, 0, 0);
                const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
                for (let i = 0; i < imageData.data.length; i += 4) {{
                    imageData.data[i] = imageData.data[i] ^ {random.randint(0, 255)};
                }}
                ctx.putImageData(imageData, 0, 0);
                return originalToDataURL.call(canvas, type, encoderOptions);
            }}
            return originalToDataURL.call(this, type, encoderOptions);
        }};

        // Navigator properties
        Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
        Object.defineProperty(navigator, 'plugins', {{ get: () => [1, 2, 3, 4, 5] }});
        Object.defineProperty(navigator, 'languages', {{ get: () => ['{fp['locale']}', 'en'] }});
        Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {fp['hardware_concurrency']} }});
        Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {fp['device_memory']} }});
        Object.defineProperty(navigator, 'maxTouchPoints', {{ get: () => {fp['max_touch_points']} }});
        Object.defineProperty(navigator, 'platform', {{ get: () => '{fp['platform']}' }});

        // Chrome runtime
        window.chrome = {{ runtime: {{}} }};

        // AudioContext
        const originalAudioContext = window.AudioContext || window.webkitAudioContext;
        if (originalAudioContext) {{
            const AudioContextProxy = function() {{
                const ctx = new originalAudioContext();
                Object.defineProperty(ctx, 'sampleRate', {{ value: {fp['audio_sample_rate']} }});
                Object.defineProperty(ctx.destination, 'maxChannelCount', {{ value: {fp['audio_channels']} }});
                return ctx;
            }};
            AudioContextProxy.prototype = originalAudioContext.prototype;
            window.AudioContext = AudioContextProxy;
            window.webkitAudioContext = AudioContextProxy;
        }}

        // Fonts
        const fontList = {json.dumps(fp['fonts'])};
        Object.defineProperty(document, 'fonts', {{
            get: () => ({{
                ready: Promise.resolve(),
                status: 'loaded',
                forEach: (callback) => fontList.forEach(font => callback({{ family: font }})),
                has: (font) => fontList.includes(font.family),
            }}),
        }});
        """
        await context.add_init_script(stealth_js)

        page = await context.new_page()
        page.set_default_timeout(PAGE_TIMEOUT)

        # Token kuzatuvchilar
        async def on_response(resp):
            nonlocal digen_token, digen_sessionid
            sc = resp.headers.get("set-cookie", "")
            if sc:
                m = re.search(r"digen-token=([^;]+)", sc)
                if m and not digen_token:
                    digen_token = m.group(1)
                    log.info(f"🔑 digen-token (cookie): {digen_token[:30]}...")
                m = re.search(r"digen-sessionid=([^;]+)", sc)
                if m and not digen_sessionid:
                    digen_sessionid = m.group(1)
                    log.info(f"🔑 digen-sessionid (cookie): {digen_sessionid}")

        async def on_request(req):
            nonlocal digen_token, digen_sessionid
            if "/api/" in req.url or "digen.ai" in req.url:
                headers = req.headers
                token = headers.get("digen-token")
                session = headers.get("digen-sessionid")
                if token and not digen_token:
                    digen_token = token
                    log.info(f"🔑 digen-token (request): {digen_token[:30]}...")
                if session and not digen_sessionid:
                    digen_sessionid = session
                    log.info(f"🔑 digen-sessionid (request): {digen_sessionid}")

        page.on("response", on_response)
        page.on("request", on_request)

        # Signup
        await page.goto(SIGNUP_URL, wait_until="domcontentloaded", timeout=60000)
        log.info("✅ Signup ochildi")
        await asyncio.sleep(random.uniform(1, 3))

        await page.wait_for_selector("#form_item_email", state="visible")
        await page.fill("#form_item_email", email)
        await asyncio.sleep(random.uniform(0.5, 1.5))

        await page.click("button.btn-submit")
        log.info("📤 Kod yuborildi")
        await asyncio.sleep(random.uniform(2, 4))

        code = await wait_for_code(gmail, timeout=CODE_TIMEOUT)

        await page.wait_for_selector("#form_item_code", state="visible", timeout=15000)
        await page.fill("#form_item_code", code)
        await asyncio.sleep(random.uniform(0.5, 1.5))

        await verify_until_password_appears(page, max_attempts=5)

        await page.wait_for_selector("#form_item_password", state="visible", timeout=10000)
        await page.wait_for_selector("#form_item_password2", state="visible", timeout=10000)
        await page.fill("#form_item_password", password)
        await asyncio.sleep(random.uniform(0.3, 0.8))
        await page.fill("#form_item_password2", password)
        await asyncio.sleep(random.uniform(0.3, 0.8))

        # Submit
        btns = await page.query_selector_all("button.btn-submit")
        clicked = False
        for btn in btns:
            txt = (await btn.inner_text()).strip().lower()
            if "гот" in txt or "done" in txt or "finish" in txt:
                await btn.click()
                log.info(f"🖱️ Submit: [{txt}]")
                clicked = True
                break
        if not clicked and btns:
            await btns[-1].click()
            log.info("🖱️ Submit (oxirgi btn-submit)")

        await asyncio.sleep(random.uniform(5, 8))

        # Modal yopish
        try:
            close = await page.wait_for_selector("button.absolute", timeout=4000)
            await close.click()
            log.info("❌ Modal yopildi")
            await asyncio.sleep(random.uniform(1, 2))
        except Exception:
            pass

        # /image sahifasi
        log.info("🔄 /image ga o'tilmoqda...")
        await page.goto(IMAGE_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(random.uniform(3, 6))

        # Textarea topish va yozish
        textarea = None
        selectors = [
            "textarea",
            "input[type='text']",
            "div[contenteditable='true']",
            "[class*='prompt']",
            "[placeholder*='Type']",
            "[placeholder*='Prompt']",
        ]
        for sel in selectors:
            try:
                textarea = await page.wait_for_selector(sel, timeout=3000)
                if textarea:
                    break
            except PlaywrightTimeout:
                continue

        if textarea:
            prompts = ["sunset", "beautiful landscape", "cyberpunk city", "fantasy art", "portrait", "anime girl", "cat", "dog", "mountain", "ocean", "forest", "space", "robot", "car", "flower"]
            prompt = random.choice(prompts)
            await textarea.fill(prompt)
            log.info(f"✍️ '{prompt}' yozildi")
            await asyncio.sleep(random.uniform(1, 2))
            await textarea.press("Enter")
            log.info("⏎ Enter bosildi – generatsiya so'rovi yuborildi")
            await asyncio.sleep(random.uniform(5, 8))
        else:
            log.warning("⚠️ Textarea topilmadi, token faqat cookie/ls dan olinadi")

        # Token va sessionni yig'ish
        if not digen_token or not digen_sessionid:
            cookies = await context.cookies()
            for c in cookies:
                if c["name"] in ("digen-token", "digen_token") and not digen_token:
                    digen_token = c["value"]
                if c["name"] in ("digen-sessionid", "digen_sessionid") and not digen_sessionid:
                    digen_sessionid = c["value"]

        if not digen_token or not digen_sessionid:
            try:
                ls = json.loads(await page.evaluate("JSON.stringify(window.localStorage)") or "{}")
                digen_token = digen_token or ls.get("digen-token") or ls.get("digen_token")
                digen_sessionid = digen_sessionid or ls.get("digen-sessionid") or ls.get("digen_sessionid")
            except Exception:
                pass

        await browser.close()

    if not digen_token or not digen_sessionid:
        raise RuntimeError("❌ Token yoki session topilmadi!")

    return {
        "email": email,
        "digen-token": digen_token,
        "digen-sessionid": digen_sessionid,
        "timestamp": datetime.now().isoformat(),
    }

# ================== NATIJANI SAQLASH ==================
def save_token(record: dict) -> None:
    tokens = []
    p = Path(TOKENS_FILE)
    if p.exists():
        try:
            tokens = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            tokens = []
    tokens.append(record)
    p.write_text(json.dumps(tokens, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info(f"💾 {TOKENS_FILE} → {len(tokens)} ta token")

# ================== PROXY TEKSHIRISH ==================
def check_proxy(proxy: str) -> bool:
    try:
        proxies = {"http": proxy, "https": proxy}
        r = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=15)
        return r.status_code == 200
    except Exception:
        return False

# ================== ASOSIY LOOP ==================
async def main():
    if TOR_PROXY and check_proxy(TOR_PROXY):
        proxy = TOR_PROXY
        log.info("✅ Tor proxy ishlaydi")
    else:
        log.error("Tor proxy ishlamayapti!")
        return

    log.info("=" * 55)
    log.info(f"  Digen.ai Bot (max random fingerprint + IP rotation) | {NUM_ACCOUNTS} ta akkaunt")
    log.info("=" * 55)

    for i in range(1, NUM_ACCOUNTS + 1):
        log.info(f"\n{'─'*45}")
        log.info(f"  AKKAUNT {i}/{NUM_ACCOUNTS}")
        log.info(f"{'─'*45}")

        try:
            acc = await create_account(proxy=proxy)
            save_token({
                "email": acc["email"],
                "digen-token": acc["digen-token"],
                "digen-sessionid": acc["digen-sessionid"],
                "timestamp": acc["timestamp"],
            })
            log.info(f"✅ Saqlandi → {acc['email']}")
        except Exception as e:
            log.error(f"❌ Xato: {e}", exc_info=True)

        if i < NUM_ACCOUNTS:
            delay = random.uniform(30, 60)
            log.info(f"⏸  {delay:.0f}s pauza...")
            await asyncio.sleep(delay)

    # Yakuniy stat
    if Path(TOKENS_FILE).exists():
        tokens = json.loads(Path(TOKENS_FILE).read_text(encoding="utf-8"))
        log.info("\n" + "=" * 55)
        log.info(f"  YAKUNLANDI  |  {len(tokens)} ta token saqlandi")
        log.info("=" * 55)
        for t in tokens[-5:]:
            log.info(f"  {t['email']}")
            log.info(f"    token:     {(t.get('digen-token') or 'YOQ')[:40]}...")
            log.info(f"    sessionid: {t.get('digen-sessionid') or 'YOQ'}")

if __name__ == "__main__":
    asyncio.run(main())
