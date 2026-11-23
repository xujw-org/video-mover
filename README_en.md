# Video Mover: An Automated Multi-Platform Content Distribution Pipeline

[简体中文](./README.md) | [English](./README_en.md)

A configurable video-processing and publishing workflow for multi-platform content operations.

The project connects file monitoring, media processing, metadata generation, scheduling, and platform-specific publishing in one pipeline. It explores how repetitive content operations can be made more consistent and observable. Each stage is an independent module that can be combined, replaced, or disabled as needed.

> Use this project only with content and accounts you are authorized to manage. Users are responsible for complying with copyright requirements, platform policies, and applicable laws.

## Context

Multi-platform publishing often involves disconnected manual steps: receiving assets, normalizing media, preparing copy, scheduling posts, and uploading the same content through different interfaces. This creates repetitive work and inconsistent execution.

Video Mover models these steps as composable tasks that can be automated, monitored, and extended. The goal is not to replace the creative work, but to hand deterministic, repetitive labor — processing, copy drafts, scheduling, publishing — to a pipeline, keeping humans on asset selection and final content review.

## Capabilities

- **Directory watching and job triggers**: continuously monitors source folders with Watchdog and starts processing jobs as new files arrive; supports unattended 24/7 operation.
- **Content differentiation toolbox**: a configurable FFmpeg/OpenCV processing chain covering auto subtitles, custom titles, background music (BGM), picture-in-picture (PIP), silent-clip removal, mirroring, rotation, cropping, fade in/out, quality adjustments, and dozens of visual operations such as background blur, frame swapping, color shifting, and texture noise. Every feature is independently configurable and freely composable, aimed at re-creation and asset-normalization scenarios.
- **GPU acceleration**: uses NVIDIA hardware encoding on compatible machines to significantly shorten batch processing time.
- **AI-assisted copy drafts**: integrates Alibaba Cloud Bailian LLM to analyze video content and draft titles and tags, which are reviewed by a human before publishing.
- **Job queues and scheduling**: configures task queues and publishing timetables through APScheduler with unified execution state.
- **Multi-platform publishing adapters**: Playwright-driven browser automation for TikTok, Douyin, Kuaishou, Bilibili, WeChat Channels, and Xiaohongshu, reusing login sessions and filling upload forms automatically.
- **Extensible architecture**: plugins and handlers extend processing steps and upload adapters; adding a platform or a processing feature does not require changing the core flow.
- **Logging and status**: full task logs and execution status for failure diagnosis and process review.

## 📸 Screenshots

<p align="center">
  <a href="https://www.bilibili.com/video/BV1txQeYyEEz" target="_blank">
    <img src="./images/cover_demo.png" alt="Application UI demo" width="800"/>
  </a>
  <br>
  <em>Application UI (click the cover to watch the demo video on Bilibili)</em>
</p>

<p align="center">
  <img src="./images/cover_script.png" alt="Script execution" width="800"/>
  <br>
  <em>Script execution in progress</em>
</p>

## Workflow

```text
Content input
    -> File watcher
    -> Video processing
    -> Metadata generation
    -> Scheduling
    -> Platform adapters
    -> Execution logs
```

## Technical Design

- `main.py`: orchestration, file management, scheduling, and plugin entry point
- `Dedup/`: FFmpeg- and OpenCV-based media processing (implements the toolbox features above)
- `Upload/`: platform adapters and account configuration
- `my_apps.yaml`: application and network settings (input folders, target platforms, proxy, schedules)

Core technologies: Python, FFmpeg, OpenCV, Playwright, Watchdog, APScheduler, and LLM APIs.

## Quick Start

### Requirements

- Windows
- Python 3.12+ (conda optional: a project `.venv` is used when conda is absent,
  and `setup.bat` installs Python itself when none is present)
- Node.js 22.x
- FFmpeg (`PATH` is used when present; on Windows `setup.bat` downloads it to
  `tools\ffmpeg` when missing)
- Chrome (optional: falls back to the Playwright Chromium installed by
  `setup.bat`; set `DOUYIN_CHROME_PATH` to pin a path)

### Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/toki-plus/video-mover.git
   cd video-mover
   ```

2. Prepare the runtime. Nothing manual is required: `setup.bat` picks, in order,

   - an existing conda environment (default name `dy`, created with
     `conda create -y -n dy python=3.12` when missing);
   - the project `.venv` when conda is not installed (created automatically);
   - a Python 3.13 install when no Python 3.12+ exists (`winget` first, then the
     python.org installer, per-user and added to `PATH`).

   To pin a specific conda environment, create it first and pass its name:

   ```bash
   conda create -y -n dy python=3.12     # optional
   setup.bat dy
   ```

3. Run `setup.bat` (pass another environment name as the first argument if needed: `setup.bat myenv`).
   It creates the environment when missing, then upgrades pip, prepares PyTorch,
   installs `requirements.txt` and `requirements-dev.txt`, installs the Playwright
   browsers, applies upstream patches, and prepares ffmpeg (downloaded to
   `tools\ffmpeg` when it is not on `PATH`).
   To re-check an existing environment:

   ```bash
   python scripts/win_env.py check --env dy
   ```

   > **Machines without a GPU**: the torch wheel that `openai-whisper` pulls on
   > Windows bundles CUDA (2-3 GB), which looks like a hang. When no NVIDIA GPU is
   > detected, `setup.bat` installs the CPU build first
   > (`--index-url https://download.pytorch.org/whl/cpu`), so the requirements step
   > does not download CUDA again. Force either build with `setup.bat --torch cpu`
   > or `setup.bat --torch cuda`.

   > **Why the `.bat` files contain no Chinese text**: cmd.exe decodes batch files with the
   > system code page (cp936 on Simplified Chinese Windows), so UTF-8 Chinese text is
   > garbled. Adding `chcp 65001` fixes the display but makes the cmd batch parser lose
   > track of byte offsets around multi-byte characters, occasionally executing half a
   > line as a command. The two `.bat` files are therefore ASCII-only: they locate the
   > interpreter and hand over to `scripts/win_env.py`, which prints all localized
   > (Chinese) messages. Please keep them ASCII-only when editing.

4. **Dependency patches (already automated)**: `scripts/apply_upstream_patches.py` applies
   the three compatibility edits to the installed third-party libraries (`f2` handlers /
   utils, WeChat Channels uploader timeout). `setup.bat` runs it automatically;
   add `--check` to only inspect. Patch verification targets `f2==0.0.1.7`, see
   [PATCHES.md](./PATCHES.md). Re-run after reinstalling or upgrading dependencies.

5. **Download the binary assets**: fonts, background music, watermark images, picture-in-
   picture video and README screenshots were removed from the repository. Run
   (`setup.bat --with-assets` does this for you):

   ```bash
   python scripts/download_assets.py
   ```

   See [ASSETS.md](./ASSETS.md).

### GUI (recommended)

If you do not want to edit YAML or type commands, double-click `gui.bat` (or
`gui.bat ENV_NAME`). The first run installs `requirements-gui.txt` (NiceGUI 2.x,
pinned to stay compatible with f2's `pydantic==2.9.*` and `websockets<13`) and
opens `http://127.0.0.1:8765/`.

The panel lets you start/stop the pipeline, edit sources, schedule, upload
settings, backfill, cookies/proxies, paths and upload scripts, validate the
config before saving, export the Douyin cookie, run the QR login, download
assets, and watch both live output and `app.log` (newest lines first). Starting a
new pipeline clears the current-run output and backs up the old `app.log` as
`app.log.prev`.

Notes:

- It listens on `127.0.0.1` only; launching `gui.bat` again opens the existing page.
- Saved config is not hot-reloaded; use “Save & Restart”.
- Processed-but-not-yet-uploaded mp4s are kept in `Upload/videos`; the next run
  uploads them directly and skips reprocessing when a matching output already exists.
- Closing the launcher console stops the pipeline. Child processes are bound to a
  Windows Job Object, so the GUI process exit also terminates `main.py`; if an
  external `main.py` is still detected, the status card offers a force-kill button
  that never targets the GUI's own child process.
  `start.bat` and `python main.py` still work independently.

### Configuration

1. Configure input folders, target platforms, account files, proxy settings, and schedules in `my_apps.yaml`.
2. If AI-assisted copy is enabled, provide API credentials through secure local configuration — never commit them.
3. Initialize account sessions and cookies when running a platform adapter for the first time.

### Update

On a machine that has already been cloned, double-click `update.bat` (or
`update.bat ENV_NAME`). It runs:

1. `git pull --ff-only`;
2. setup again: dependencies, Playwright, upstream patches, ffmpeg;
3. download missing binary assets (existing files are skipped).

Environment discovery matches `setup.bat`: a conda env first, then the project
`.venv`, then conda base. If none exists, `scripts/bootstrap_python.ps1` installs
Python 3.12+ and a `.venv` is created, so a PC without Python can run this script
directly.

The updater only follows `main`; it stops with a `git switch main` hint on other
branches. If an old clone's `origin` points elsewhere, it is rewritten to
`https://git.xujw.top/xujinwen/video-mover.git` before pulling, so a stale remote
cannot make `update.bat` silently keep old code.

Uncommitted changes are auto-stashed with `git stash push -u` and restored with
`git stash pop` after a successful update. If the pull or setup fails, the
changes stay in the stash and the script prints the recovery command. Use
`python scripts/win_env.py update --no-autostash` to stop instead.

If the pull fails because of divergent branches, network or credential problems,
the script stops immediately and does not touch dependencies.
Start with `gui.bat` or `start.bat` afterwards.

`my_apps.yaml`, `.env` and `Upload/cookies/` are local files and are not updated
by `git pull`.

### Run

Double-click `gui.bat` (GUI, recommended; see “GUI” above), or `start.bat`
(or `start.bat env-name` from a shell), or execute directly:

```bash
python main.py
```

`start.bat` resolves the interpreter the same way `setup.bat` does (conda env `dy`,
then the project `.venv`), clears the historical mp4 files in `Upload\videos` and
then starts `main.py`. To only verify the environment without starting:
`start.bat dy --dry-run`.

The program opens a browser and starts the tasks; complete the first login as prompted, then the pipeline runs automatically.

## Current Limitations

- Platform adapters may require updates when third-party pages or interfaces change.
- Some upstream dependencies have version-specific compatibility requirements.
- The project does not yet include comprehensive automated tests or CI.
- API keys, cookies, and account configuration must never be committed to the repository.

## What This Project Demonstrates

The primary focus is workflow decomposition and cross-system orchestration: turning file watching, media processing, LLM calls, scheduling, and browser automation into an observable, recoverable pipeline — defining task boundaries, integrating third-party systems, recording failures, and leaving clear extension points. It is not intended as a showcase of a single media-processing algorithm. Details such as "upstream libraries need manual patches to stay compatible with live platform interfaces" also illustrate the hidden integration costs typical of real-world automation projects.

## 📂 More Projects

- [ai-highlight-clip](https://github.com/toki-plus/ai-highlight-clip) — Long-video smart triage: Whisper transcription + LLM scoring + human review
- [ai-ttv-workflow](https://github.com/toki-plus/ai-ttv-workflow) — Desktop text-to-video workflow with human-in-the-loop checkpoints
- [ai-video-workflow](https://github.com/toki-plus/ai-video-workflow) — Multi-model AIGC video pipeline orchestrating image, video and music services
- [ai-mixed-cut](https://github.com/toki-plus/ai-mixed-cut) — Video re-creation workflow via structured asset library and script reassembly
- [ai-trader-for-mt4](https://github.com/toki-plus/ai-trader-for-mt4) — LLM×MT4 controlled-execution framework: constrained tools, risk rules, state management
- [ai-trader-for-mt5](https://github.com/toki-plus/ai-trader-for-mt5) — AI trading assistant and EA engineering framework for MetaTrader 5
- [auto-usps-tracker](https://github.com/toki-plus/auto-usps-tracker) — Batch shipment tracking and Excel reporting for cross-border e-commerce
- [AB-Video-Deduplicator](https://github.com/toki-plus/AB-Video-Deduplicator) — Experimental video re-creation tool based on high-frame-rate blending
- [netease-downloader](https://github.com/toki-plus/netease-downloader) — Netease Cloud Music desktop downloader: QR login, queue, ID3 tagging

## License

See [LICENSE](./LICENSE).
