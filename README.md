# mi-imgd
```
           _       _                     _ 
 _ __ ___ (_)     (_)_ __ ___   __ _  __| |
| '_ ` _ \| |_____| | '_ ` _ \ / _` |/ _` |
| | | | | | |_____| | | | | | | (_| | (_| |
|_| |_| |_|_|     |_|_| |_| |_|\__, |\__,_|
                               |___/       
```
## install
```bash
pip install .
```

## Usage
```bash
$ mimgd -h
usage: mimgd [-h] --links LINKS [LINKS ...] [--output-dir OUTPUT_DIR]
             [--processes PROCESSES]

mi-imgd Misskey画像クローラー

options:
  -h, --help            show this help message and exit
  --links, -l LINKS [LINKS ...]
                        クロールするMisskeyユーザーページのURL (複数指定可能)
  --output-dir, -o OUTPUT_DIR
                        画像を保存する出力ディレクトリ (デフォルト: misskey_images)
  --processes, -p PROCESSES
                        同時に実行するプロセス数 (デフォルト: CPU論理コア数と対象URL数のうち小さい方)

```

