REM Video Mover 安装脚本（Windows）
REM 依赖版本已锁定在 requirements.txt（锁定日期 2026-11-12）。
REM 安装后会自动运行上游兼容补丁脚本，详见 PATCHES.md。
python -m pip install --upgrade pip
pip install -r requirements.txt
python scripts\apply_upstream_patches.py
playwright install chromium firefox
REM 首次运行前还需要下载已移出仓库的二进制资产（字体 / 音乐 / 水印图等），见 ASSETS.md：
REM python scripts\download_assets.py
