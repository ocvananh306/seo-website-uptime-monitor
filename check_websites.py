import os
import random
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import json
from datetime import datetime, timezone, timedelta

# Danh sách 11 website cần kiểm tra
WEBSITES = [
    "https://synctrack.io/",
    "https://twoowls.io/",
    "https://letsmetrix.com/",
    "https://blockifyapp.com/",
    "https://consentik.com/",
    "https://www.omegatheme.com/",
    "https://trustifyreview.app/",
    "https://dingdoong.io/",
    "https://paretoaov.com/",
    "https://quotesnap.net/",
    "https://tagfly.io/"
]

# Số lượng URL ngẫu nhiên lấy từ sitemap của mỗi website (ngoài trang chủ)
RANDOM_URLS_PER_SITE = 3

# Lấy Webhook URL từ biến môi trường GitHub Secrets
LARK_WEBHOOK_URL = os.environ.get("LARK_WEBHOOK_URL", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}


def fetch_url(url, timeout=15):
    """Gửi HTTP GET request và trả về (status_code, content_bytes, error_message)."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.getcode(), response.read(), "OK"
    except urllib.error.HTTPError as e:
        return e.code, b"", f"HTTP Error {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return 0, b"", f"Connection/DNS Error: {e.reason}"
    except Exception as e:
        return 0, b"", f"Timeout/Unexpected Error: {str(e)}"


def parse_sitemap_urls(xml_bytes):
    """Trích xuất danh sách URL từ nội dung XML của sitemap."""
    urls = []
    sub_sitemaps = []
    try:
        root = ET.fromstring(xml_bytes)
        for elem in root.iter():
            tag = elem.tag.split("}")[-1]  # Bỏ qua XML namespace
            if tag == "loc" and elem.text:
                loc_text = elem.text.strip()
                if loc_text.endswith(".xml"):
                    sub_sitemaps.append(loc_text)
                else:
                    urls.append(loc_text)
    except ET.ParseError:
        pass
    return urls, sub_sitemaps


def get_random_urls_from_sitemap(domain, count):
    """Đọc sitemap.xml (hỗ trợ cả Sitemap Index) và lấy ngẫu nhiên N URL."""
    sitemap_url = domain.rstrip("/") + "/sitemap.xml"
    code, content, _ = fetch_url(sitemap_url, timeout=15)
    if code != 200 or not content:
        return []

    urls, sub_sitemaps = parse_sitemap_urls(content)

    # Nếu là Sitemap Index (chứa các sitemap con), chọn ngẫu nhiên 1 sitemap con để quét
    if not urls and sub_sitemaps:
        chosen_sub = random.choice(sub_sitemaps)
        sub_code, sub_content, _ = fetch_url(chosen_sub, timeout=15)
        if sub_code == 200 and sub_content:
            urls, _ = parse_sitemap_urls(sub_content)

    if not urls:
        return []

    sample_size = min(count, len(urls))
    return random.sample(urls, sample_size)


def send_lark_alert(errors, timestamp_str):
    """Gửi cảnh báo qua Lark Custom Bot Webhook."""
    if not LARK_WEBHOOK_URL:
        print("⚠️ Chưa cấu hình LARK_WEBHOOK_URL trong GitHub Secrets. Bỏ qua gửi thông báo.")
        return

    error_lines = []
    for err in errors:
        status_label = "DOWN / TIMEOUT" if err["code"] == 0 else f"HTTP {err['code']}"
        error_lines.append(f"• [{status_label}] {err['url']}\n  Chi tiết: {err['message']}")

    message_text = (
        f"🚨 CẢNH BÁO WEBSITE LỖI 5XX / DOWN ({timestamp_str})\n\n"
        f"Phát hiện {len(errors)} URL gặp sự cố:\n\n"
        + "\n\n".join(error_lines)
    )

    payload = json.dumps({
        "msg_type": "text",
        "content": {"text": message_text}
    }).encode("utf-8")

    req = urllib.request.Request(
        LARK_WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            print(f"✅ Đã gửi cảnh báo tới Lark (Status: {res.getcode()})")
    except Exception as e:
        print(f"❌ Lỗi khi gửi Webhook tới Lark: {e}")


def main():
    vn_tz = timezone(timedelta(hours=7))
    now_str = datetime.now(vn_tz).strftime("%Y-%m-%d %H:%M:%S (GMT+7)")
    print(f"=== Bắt đầu kiểm tra 11 website lúc {now_str} ===\n")

    critical_errors = []

    for domain in WEBSITES:
        clean_domain = domain.rstrip("/") + "/"
        urls_to_check = [clean_domain]
        random_urls = get_random_urls_from_sitemap(clean_domain, RANDOM_URLS_PER_SITE)

        for u in random_urls:
            if u not in urls_to_check:
                urls_to_check.append(u)

        for target_url in urls_to_check:
            code, _, msg = fetch_url(target_url, timeout=15)
            is_critical = (code >= 500 or code == 0)

            if is_critical:
                print(f"[ERROR - {code}] {target_url} -> {msg}")
                critical_errors.append({
                    "domain": clean_domain,
                    "url": target_url,
                    "code": code,
                    "message": msg
                })
            else:
                print(f"[OK - {code}] {target_url}")

            time.sleep(0.3)

    print(f"\n=== Hoàn tất kiểm tra. Tổng số lỗi nghiêm trọng (5xx/Down): {len(critical_errors)} ===")

    if critical_errors:
        send_lark_alert(critical_errors, now_str)


if __name__ == "__main__":
    main()
