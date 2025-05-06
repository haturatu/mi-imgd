#!/usr/bin/python3
#!/usr/bin/python3
import os
import re
import argparse
from playwright.sync_api import sync_playwright
import requests
from urllib.parse import urlparse
import time
import hashlib

def get_username_from_url(url):
    match = re.search(r'@([^/]+)', url)
    if match:
        return match.group(1)
    return os.path.basename(url).replace('@', '')

def scrape_misskey_images(user_urls, output_dir="misskey_images"):
    os.makedirs(output_dir, exist_ok=True)

    downloaded_hashes = set()
    processed_thumbnails = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        for user_url in user_urls:
            # ユーザー名を取得
            username = get_username_from_url(user_url)
            user_dir = os.path.join(output_dir, username)
            os.makedirs(user_dir, exist_ok=True)

            print(f"\nユーザー: {username} の処理を開始します (ディレクトリ: {user_dir})")

            page.goto(user_url)

            no_new_images_count = 0
            max_no_new_attempts = 3  # 新規画像がない場合のリトライ回数

            while no_new_images_count < max_no_new_attempts:
                print(f"\n新規画像を取得中... (試行 {no_new_images_count + 1}/{max_no_new_attempts})")

                last_height = page.evaluate("document.body.scrollHeight")
                page.mouse.wheel(0, 10000)
                page.mouse.wheel(0, 10000)
                page.wait_for_timeout(3000)

                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    print("取得しました。")
                    no_new_images_count += 1
                else:
                    print(f"height: {new_height}")

                image_urls = set()
                img_elements = page.query_selector_all("img")

                for img in img_elements:
                    src = img.get_attribute("src")
                    if src and "media.misskeyusercontent.jp/io/thumbnail-" in src and src not in processed_thumbnails:
                        image_urls.add(src)

                if not image_urls:
                    print("新規の画像が見つかりませんでした。")
                    no_new_images_count += 1
                    continue
                else:
                    no_new_images_count = 0
                    print(f"新規画像 {len(image_urls)} 枚を処理します")

                # 新規サムネイル画像を処理
                for i, thumb_url in enumerate(image_urls, 1):
                    processed_thumbnails.add(thumb_url)  # 処理済みとしてマーク
                    max_retries = 2  # リトライは2回まで
                    retry_count = 0
                    success = False

                    while retry_count < max_retries and not success:
                        try:
                            print(f"\n処理中 ({i}/{len(image_urls)}), 試行 {retry_count + 1}/{max_retries}: {thumb_url}")

                            with context.expect_page() as new_page_info:
                                page.click(f'img[src="{thumb_url}"]', button="middle")
                            new_page = new_page_info.value
                            new_page.wait_for_load_state("networkidle")
                            time.sleep(2)

                            img_element = new_page.query_selector("img")
                            img_url = None

                            if img_element:
                                img_url = img_element.get_attribute("src")

                                if (img_url and
                                    "media.misskeyusercontent.jp/io/" in img_url and
                                    "thumbnail-" not in img_url):
                                    print(f"画像URLを取得: {img_url}")
                                    success = True
                                else:
                                    print(f"取得したURLが適切でない可能性があります: {img_url}")
                                    img_url = None
                            else:
                                print("画像要素が見つかりませんでした")
                                if ("media.misskeyusercontent.jp/io/" in new_page.url and
                                    "thumbnail-" not in new_page.url):
                                    img_url = new_page.url
                                    print(f"ページURLから画像URLを取得: {img_url}")
                                    success = True

                            if img_url:
                                try:
                                    if not img_url.startswith(('http://', 'https://')):
                                        img_url = 'https://' + img_url

                                    response = requests.get(img_url, stream=True, headers={
                                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                                    })
                                    response.raise_for_status()

                                    img_data = response.content

                                    img_hash = hashlib.md5(img_data).hexdigest()

                                    # 重複チェック
                                    if img_hash in downloaded_hashes:
                                        print(f"既にダウンロード済みの画像です（ハッシュ: {img_hash}）。スキップします。")
                                    else:
                                        # URLからファイル名を生成
                                        parsed = urlparse(img_url)
                                        filename = os.path.basename(parsed.path)

                                        # "webpublic" から始まるファイル名はスキップ
                                        if filename.startswith("webpublic"):
                                            print(f"'webpublic'から始まるファイル名のためスキップします: {filename}")
                                            continue

                                        save_path = os.path.join(user_dir, filename)

                                        counter = 1
                                        name, ext = os.path.splitext(filename)
                                        while os.path.exists(save_path):
                                            save_path = os.path.join(user_dir, f"{name}_{counter}{ext}")
                                            counter += 1

                                        # 保存
                                        with open(save_path, "wb") as f:
                                            f.write(img_data)

                                        # ハッシュを記録
                                        downloaded_hashes.add(img_hash)

                                        print(f"保存しました ({i}/{len(image_urls)}): {save_path}")
                                except Exception as e:
                                    print(f"ダウンロードに失敗しました: {img_url} - {str(e)}")

                            new_page.close()

                        except Exception as e:
                            print(f"試行 {retry_count + 1} でエラーが発生しました: {str(e)}")
                            if retry_count < max_retries - 1:
                                print("2秒待機して再試行します...")
                                time.sleep(2)

                        retry_count += 1

                    if not success:
                        print(f"最大試行回数に達しましたが、画像URLを取得できませんでした: {thumb_url}")

                time.sleep(3)

            print(f"\n{user_url} の画像処理が完了しました。")

        print("\n全ての処理が完了しました。")
        print(f"処理したサムネイル数: {len(processed_thumbnails)}")
        print(f"ダウンロードした一意の画像数: {len(downloaded_hashes)}")
        browser.close()

def main():
    parser = argparse.ArgumentParser(description='mi-imgd Misskey画像クローラー')
    parser.add_argument('--links', '-l', nargs='+', required=True,
                        help='クロールするMisskeyユーザーページのURL (複数指定可能)')
    parser.add_argument('--output-dir', '-o', default='misskey_images',
                        help='画像を保存する出力ディレクトリ (デフォルト: misskey_images)')

    args = parser.parse_args()

    print(f"クロール対象URL: {args.links}")
    print(f"出力ディレクトリ: {args.output_dir}")

    scrape_misskey_images(args.links, args.output_dir)

if __name__ == "__main__":
    main()
