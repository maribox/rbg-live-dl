import os
import json
import re
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from yt_dlp import YoutubeDL  # type: ignore

def load_credentials(filepath: str = "credentials.json") -> tuple[str, str]:
    with open(filepath, "r") as f:
        data = json.load(f)
    return data["username"], data["password"]

def wait_for_element(driver, by, selector, timeout: int = 20):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by, selector))
    )

def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', '_', name)
    return re.sub(r'\s+', ' ', cleaned).strip()

def extract_year_or_fallback(relative_path: str) -> str:
    m = re.search(r"/(20\d{2})(?:/|$)", relative_path)
    if m:
        return m.group(1)
    return relative_path.lstrip("/")

def automated_login(driver, username: str, password: str):
    driver.get("https://live.rbg.tum.de")
    wait_for_element(driver, By.CSS_SELECTOR, "#user-context > a").click()
    wait_for_element(driver, By.CSS_SELECTOR, "#content > section > article > a").click()
    wait_for_element(driver, By.CSS_SELECTOR, "#username").send_keys(username)
    driver.find_element(By.CSS_SELECTOR, "#password").send_keys(password)
    driver.find_element(By.CSS_SELECTOR, "#btnLogin").click()
    wait_for_element(driver, By.CSS_SELECTOR, "#user-context a[href*='logout']")
    print("✅ Logged in successfully")

def extract_video_info(driver, video_page_url: str) -> tuple[str, str, str]:
    driver.get(video_page_url)

    # 1) HLS URL
    source = wait_for_element(driver,
        By.CSS_SELECTOR,
        "#video-comb_html5_api > source:nth-child(1)"
    )
    hls_url = source.get_attribute("src")
    if not hls_url or not hls_url.strip():
        raise RuntimeError("HLS URL not found")
    hls_url = hls_url.strip()

    # 2) Link element → full href → relative path → year or fallback
    link = wait_for_element(driver,
        By.CSS_SELECTOR,
        ".sm\\:flex-row > div:nth-child(1) > a:nth-child(1)"
    )
    full_href = link.get_attribute("href") or ""
    rel_path = urlparse(full_href).path
    year_or_path = extract_year_or_fallback(rel_path)

    # 3) span.hover:text-1 inner text
    span = link.find_element(By.CSS_SELECTOR, "span.hover\\:text-1")
    span_text = re.sub(r'\s+', ' ', span.text or "").strip()

    # 4) h1.font-bold inner text
    h1 = wait_for_element(driver,
        By.CSS_SELECTOR,
        "h1.font-bold"
    )
    h1_text = re.sub(r'\s+', ' ', h1.text or "").strip()

    # Build folder (span + year_or_path) and file (h1)
    folder_base = f"{span_text} - {year_or_path}"
    safe_folder = sanitize_filename(folder_base)
    safe_file   = sanitize_filename(h1_text)

    print(f"📂 Folder: out/{safe_folder}")
    print(f"🎥 File: {safe_file}.mp4")
    return hls_url, safe_folder, safe_file

def download_hls(hls_url: str, folder: str, file_name: str):
    out_dir = os.path.join("out", folder)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{file_name}.mp4")

    ydl_opts = {
        'outtmpl': out_path,
        'format': 'best',
        'quiet': False,
        'nocheckcertificate': True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([hls_url])

    print(f"✅ Download complete: {out_path}")

def main():
    username, password = load_credentials()
    driver = webdriver.Chrome()

    try:
        automated_login(driver, username, password)
        hls_url, folder, file_name = extract_video_info(
            driver,
            "https://live.rbg.tum.de/w/ma0005/1461"
        )
        print(f"🔗 HLS URL: {hls_url}")
        download_hls(hls_url, folder, file_name)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
