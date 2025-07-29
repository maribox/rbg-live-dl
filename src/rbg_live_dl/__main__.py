import os
import sys
import json
import re
from urllib.parse import urlparse, urljoin
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
    # Extract a 4-digit year from the path (e.g. "/course/2021/S/ma0005").
    # If none found, return the entire relative path without leading slash.
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

def get_pinned_courses(driver) -> list[tuple[str, str]]:
    wait_for_element(driver, By.CSS_SELECTOR, "article.tum-live-side-navigation-group:nth-child(3) > a")
    anchors = driver.find_elements(By.CSS_SELECTOR, "article.tum-live-side-navigation-group:nth-child(3) > a")
    courses = []
    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue
        full_url = urljoin("https://live.rbg.tum.de", href)
        name = re.sub(r'\s+', ' ', a.text or "").strip()
        courses.append((name, full_url))
    return courses

def get_video_urls(driver, listing_page_url: str) -> list[str]:
    driver.get(listing_page_url)
    wait_for_element(driver, By.CSS_SELECTOR, "article.mb-8 a.block.mb-2")
    anchors = driver.find_elements(By.CSS_SELECTOR, "article.mb-8 a.block.mb-2")
    urls = []
    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue
        urls.append(urljoin("https://live.rbg.tum.de", href))
    return urls

def extract_video_info(driver, video_page_url: str) -> tuple[str, str, str]:
    driver.get(video_page_url)

    # HLS URL
    source = wait_for_element(driver, By.CSS_SELECTOR, "#video-comb_html5_api > source:nth-child(1)")
    hls_url = source.get_attribute("src") or ""
    if not hls_url.strip():
        raise RuntimeError("HLS URL not found")
    hls_url = hls_url.strip()

    # Link element → full href → relative path → year or fallback
    link = wait_for_element(driver, By.CSS_SELECTOR, ".sm\\:flex-row > div:nth-child(1) > a:nth-child(1)")
    full_href = link.get_attribute("href") or ""
    rel_path = urlparse(full_href).path
    year_or_path = extract_year_or_fallback(rel_path)

    # span.hover:text-1 inner text
    span = link.find_element(By.CSS_SELECTOR, "span.hover\\:text-1")
    span_text = re.sub(r'\s+', ' ', span.text or "").strip()

    # h1.font-bold inner text
    h1 = wait_for_element(driver, By.CSS_SELECTOR, "h1.font-bold")
    h1_text = re.sub(r'\s+', ' ', h1.text or "").strip()

    # Build folder (span + year_or_path) and file (h1_text)
    folder_base = f"{span_text} - {year_or_path}"
    safe_folder = sanitize_filename(folder_base)
    safe_file = sanitize_filename(h1_text)

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
    overwrite = "--overwrite" in sys.argv
    username, password = load_credentials()
    driver = webdriver.Chrome()
    try:
        automated_login(driver, username, password)

        # 1) Get pinned courses
        pinned = get_pinned_courses(driver)
        print("🔔 Pinned courses:")
        for name, url in pinned:
            print(f"  • {name} → {url}")

        # 2) For each course, grab its video URLs and download
        for course_name, course_url in pinned:
            print(f"\n▶ Processing course: {course_name}")
            video_urls = get_video_urls(driver, course_url)
            n_videos = len(video_urls)
            for idx, vid_url in enumerate(video_urls):
                # Reverse counter: newest gets highest, oldest gets 01
                counter = n_videos - idx
                print(f"   → Video page: {vid_url}")
                folder = "unknown"
                file_name = "unknown"
                last_exception = None
                for attempt in range(1, 4):
                    try:
                        hls_url, folder, file_name = extract_video_info(driver, vid_url)
                        counter_str = f"{counter:02d} "
                        file_name_with_counter = counter_str + file_name
                        out_dir = os.path.join("out", folder)
                        out_path = os.path.join(out_dir, f"{file_name_with_counter}.mp4")
                        if not overwrite and os.path.isfile(out_path) and os.path.getsize(out_path) > 1_000_000:
                            print(f"⏩ Skipping (already exists and is not empty): {out_path}")
                            break
                        download_hls(hls_url, folder, file_name_with_counter)
                        last_exception = None
                        break
                    except Exception as e:
                        last_exception = e
                        print(f"⚠️  Attempt {attempt} failed for {vid_url}: {e}")
                        if attempt < 3:
                            import time
                            time.sleep(2)
                if last_exception is not None:
                    import traceback
                    out_dir = os.path.join("out", folder if folder else "out")
                    os.makedirs(out_dir, exist_ok=True)
                    error_file = os.path.join(out_dir, f"{counter:02d} {file_name}")
                    with open(error_file, "w", encoding="utf-8") as f:
                        f.write(f"Download failed for {vid_url}\n\n")
                        f.write(str(last_exception) + "\n\n")
                        f.write(traceback.format_exc())
                    print(f"❌ Download failed after 3 attempts: {error_file}")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
