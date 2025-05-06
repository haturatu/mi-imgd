# mi-imgd
## install
```bash
pip install -r requirements.txt
playwright install
```

## Usage
```bash
$ python3 ./mimgd.py -h
usage: mimgd.py [-h] --links LINKS [LINKS ...] [--output-dir OUTPUT_DIR]

mi-imgd Misskey画像クローラー

options:
  -h, --help            show this help message and exit
  --links, -l LINKS [LINKS ...]
                        クロールするMisskeyユーザーページのURL (複数指定可能)
  --output-dir, -o OUTPUT_DIR
                        画像を保存する出力ディレクトリ (デフォルト: misskey_images)
```
