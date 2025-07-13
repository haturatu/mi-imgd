#!/usr/bin/python3
import os
import re
import argparse
from playwright.sync_api import sync_playwright
import time
import hashlib
from urllib.parse import urlparse
import multiprocessing
from functools import partial
import asyncio
import aiohttp
import logging
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(processName)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_username_from_url(url):
    match = re.search(r'@([^/]+)', url)
    if match:
        return match.group(1)
    return os.path.basename(url).replace('@', '')

async def download_single_image(session, img_url, user_dir, downloaded_hashes):
    try:
        if not img_url.startswith(('http://', 'https://')):
            img_url = 'https://' + img_url

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        async with session.get(img_url, headers=headers) as response:
            if response.status != 200:
                logger.error(f"ダウンロード失敗 (ステータス {response.status}): {img_url}")
                return None
                
            img_data = await response.read()
            img_hash = hashlib.md5(img_data).hexdigest()

            if img_hash in downloaded_hashes:
                logger.info(f"既にダウンロード済みの画像です（ハッシュ: {img_hash[:6]}...）。スキップします。")
                return None
                
            parsed = urlparse(img_url)
            filename = os.path.basename(parsed.path)

            save_path = os.path.join(user_dir, filename)
            
            if os.path.exists(save_path):
                with open(save_path, "rb") as f:
                    existing_hash = hashlib.md5(f.read()).hexdigest()
                if existing_hash == img_hash:
                    logger.info(f"同一内容のファイルが既に存在します: {save_path}")
                    return None
                    
                counter = 1
                name, ext = os.path.splitext(filename)
                while os.path.exists(save_path):
                    new_path = os.path.join(user_dir, f"{name}_{counter}{ext}")
                    if os.path.exists(new_path):
                        with open(new_path, "rb") as f:
                            existing_hash = hashlib.md5(f.read()).hexdigest()
                        if existing_hash == img_hash:
                            logger.info(f"同一内容のファイルが既に存在します: {new_path}")
                            return None
                        counter += 1
                    else:
                        save_path = new_path
                        break

            with open(save_path, "wb") as f:
                f.write(img_data)

            logger.info(f"保存しました: {save_path}")
            return img_hash

    except Exception as e:
        logger.error(f"ダウンロードに失敗しました: {img_url} - {str(e)}")
        return None

async def download_images_async(img_urls, user_dir, downloaded_hashes):
    conn = aiohttp.TCPConnector(limit=30)  # 同時接続数を制限
    timeout = aiohttp.ClientTimeout(total=30)  # タイムアウト設定
    lock = asyncio.Lock()
    
    async with aiohttp.ClientSession(connector=conn, timeout=timeout) as session:
        tasks = []
        for img_url in img_urls:
            task = download_single_image(session, img_url, user_dir, downloaded_hashes)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        new_hashes = [h for h in results if h is not None]
        
        async with lock:
            for h in new_hashes:
                if h not in downloaded_hashes:
                    downloaded_hashes.append(h)
        
        return len(new_hashes)

def process_single_user(user_url, output_dir="misskey_images", shared_hashes=None):
    username = get_username_from_url(user_url)
    user_dir = os.path.join(output_dir, username)
    os.makedirs(user_dir, exist_ok=True)

    logger.info(f"ユーザー: {username} の処理を開始します (ディレクトリ: {user_dir})")
    
    if shared_hashes is None:
        downloaded_hashes = set()
        for root, _, files in os.walk(output_dir):
            for file in files:
                if file.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                    try:
                        file_path = os.path.join(root, file)
                        with open(file_path, 'rb') as f:
                            file_hash = hashlib.md5(f.read()).hexdigest()
                            downloaded_hashes.add(file_hash)
                    except Exception as e:
                        logger.error(f"既存ファイルのハッシュ計算中にエラー: {file} - {str(e)}")
        logger.info(f"既存画像のハッシュを {len(downloaded_hashes)} 件読み込みました")
    else:
        downloaded_hashes = shared_hashes
        
    processed_thumbnails = set()
    total_images_downloaded = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(user_url)
        page.wait_for_load_state("networkidle")

        try:
            note_button = page.query_selector('button._button:has-text("ノート")')
            if note_button:
                note_button.click()
                page.wait_for_timeout(2000)
            else:
                logger.warning("警告: 正常に解析できませんでした。不要な画像をクロールする場合があります。")

            file_button = page.query_selector('button._button:has-text("ファイル付き")')
            if file_button:
                file_button.click()
                page.wait_for_timeout(2000)
            else:
                logger.warning("警告: 正常に解析できませんでした。不要な画像をクロールする場合があります。")
        except Exception as e:
            logger.error(f"解析中にエラーが発生しました: {str(e)}")

        no_new_images_count = 0
        max_no_new_attempts = 3  # 新規画像がない場合のリトライ回数

        while no_new_images_count < max_no_new_attempts:
            logger.info(f"新規画像を取得中... (試行 {no_new_images_count + 1}/{max_no_new_attempts})")

            last_height = page.evaluate("document.body.scrollHeight")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(3000)

            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                logger.info("スクロール終了")
                no_new_images_count += 1
            else:
                logger.info(f"height: {new_height}")

            image_urls = set()
            img_elements = page.query_selector_all("img")

            for img in img_elements:
                src = img.get_attribute("src")
                if src and "media.misskeyusercontent.jp/io/thumbnail-" in src and src not in processed_thumbnails:
                    image_urls.add(src)
                    processed_thumbnails.add(src)  # 処理済みとしてマーク

            if not image_urls:
                logger.info("新規の画像が見つかりませんでした。")
                no_new_images_count += 1
                continue
            else:
                no_new_images_count = 0
                logger.info(f"新規サムネイル画像 {len(image_urls)} 枚を処理します")

            original_image_urls = []
            
            for i, thumb_url in enumerate(image_urls, 1):
                max_retries = 2
                retry_count = 0
                success = False

                while retry_count < max_retries and not success:
                    try:
                        logger.info(f"サムネイル処理中 ({i}/{len(image_urls)}), 試行 {retry_count + 1}/{max_retries}")

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
                                logger.info(f"画像URLを取得: {img_url}")
                                original_image_urls.append(img_url)
                                success = True
                            else:
                                logger.warning(f"取得したURLが適切でない可能性があります: {img_url}")
                        else:
                            logger.warning("画像要素が見つかりませんでした")
                            if ("media.misskeyusercontent.jp/io/" in new_page.url and
                                "thumbnail-" not in new_page.url):
                                img_url = new_page.url
                                logger.info(f"ページURLから画像URLを取得: {img_url}")
                                original_image_urls.append(img_url)
                                success = True

                        new_page.close()

                    except Exception as e:
                        logger.error(f"試行 {retry_count + 1} でエラーが発生しました: {str(e)}")
                        if retry_count < max_retries - 1:
                            logger.info("2秒待機して再試行します...")
                            time.sleep(2)

                    retry_count += 1

                if not success:
                    logger.warning(f"最大試行回数に達しましたが、画像URLを取得できませんでした: {thumb_url}")

            if original_image_urls:
                logger.info(f"{len(original_image_urls)} 枚の画像を非同期ダウンロードします")
                
                with ThreadPoolExecutor(max_workers=1) as executor:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    future = executor.submit(
                        lambda: loop.run_until_complete(
                            download_images_async(original_image_urls, user_dir, downloaded_hashes)
                        )
                    )
                    downloaded_count = future.result()
                    total_images_downloaded += downloaded_count
                    
                logger.info(f"一括ダウンロード完了: {downloaded_count} 枚")
            
            time.sleep(2)

        logger.info(f"\n{user_url} の画像処理が完了しました。")
        browser.close()
    
    return len(processed_thumbnails), total_images_downloaded

def scrape_misskey_images(user_urls, output_dir="misskey_images", max_processes=None):
    os.makedirs(output_dir, exist_ok=True)
    
    if max_processes is None:
        max_processes = min(len(user_urls), multiprocessing.cpu_count())
    
    logger.info(f"合計 {len(user_urls)} 件のURLを {max_processes} プロセスで処理します...")
    
    shared_hashes = []  # set()からlist()に変更
    for root, _, files in os.walk(output_dir):
        for file in files:
            if file.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                try:
                    file_path = os.path.join(root, file)
                    with open(file_path, 'rb') as f:
                        file_hash = hashlib.md5(f.read()).hexdigest()
                        shared_hashes.append(file_hash)  # .add()から.append()に変更
                except Exception as e:
                    logger.error(f"既存ファイルのハッシュ計算中にエラー: {file} - {str(e)}")
    
    logger.info(f"既存画像の重複確認用ハッシュを {len(shared_hashes)} 件読み込みました")
    
    with multiprocessing.Manager() as manager:
        manager_shared_hashes = manager.list(shared_hashes)
        
        process_user_with_output_dir = partial(
            process_single_user, 
            output_dir=output_dir,
            shared_hashes=manager_shared_hashes
        )
        
        with multiprocessing.Pool(processes=max_processes) as pool:
            results = pool.map(process_user_with_output_dir, user_urls)
    
    total_thumbnails = sum(result[0] for result in results)
    total_downloads = sum(result[1] for result in results)
    
    logger.info("\n全ての処理が完了しました。")
    logger.info(f"処理したサムネイル数: {total_thumbnails}")
    logger.info(f"ダウンロードした一意の画像数: {total_downloads}")
    
    deduplicate_images(output_dir)
    
    return total_thumbnails, total_downloads

def deduplicate_images(output_dir):
    logger.info("ダウンロード後の重複確認を行っています...")
    
    file_hashes = {}
    duplicates = []
    
    for root, _, files in os.walk(output_dir):
        for file in files:
            if file.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'rb') as f:
                        file_hash = hashlib.md5(f.read()).hexdigest()
                    
                    if file_hash in file_hashes:
                        # 重複を検出
                        duplicates.append(file_path)
                        logger.info(f"重複画像を検出: {file_path} (元ファイル: {file_hashes[file_hash]})")
                    else:
                        file_hashes[file_hash] = file_path
                        
                except Exception as e:
                    logger.error(f"ファイルハッシュ計算中にエラー: {file_path} - {str(e)}")
    
    # 検出された重複を削除
    for dup_file in duplicates:
        try:
            os.remove(dup_file)
            logger.info(f"重複ファイルを削除: {dup_file}")
        except Exception as e:
            logger.error(f"重複ファイル削除中にエラー: {dup_file} - {str(e)}")
    
    logger.info(f"重複確認完了: {len(duplicates)} 件の重複ファイルを削除しました")

def main():
    parser = argparse.ArgumentParser(description='mi-imgd Misskey画像クローラー')
    parser.add_argument('--links', '-l', nargs='+', required=True,
                        help='クロールするMisskeyユーザーページのURL (複数指定可能)')
    parser.add_argument('--output-dir', '-o', default='misskey_images',
                        help='画像を保存する出力ディレクトリ (デフォルト: misskey_images)')
    parser.add_argument('--processes', '-p', type=int, default=None,
                        help='同時に実行するプロセス数 (デフォルト: CPU論理コア数と対象URL数のうち小さい方)')

    args = parser.parse_args()

    logger.info(f"クロール対象URL: {args.links}")
    logger.info(f"出力ディレクトリ: {args.output_dir}")
    
    scrape_misskey_images(args.links, args.output_dir, args.processes)

if __name__ == "__main__":
    multiprocessing.freeze_support()  # Windows対応
    main()
