# Smart Finder

A private search engine for your own files, running on your own computer. Point it at folders and it indexes them where they are — documents, photos, videos, audio — so you can search by words, meaning, pictures, faces, people's names, voice notes or sounds, and chat with an AI about what it finds.

- **No copies.** Folders are indexed in place; each keeps a small hidden `.smartfind` index. Only files uploaded from a browser are stored (in the Uploads library).
- **No limits.** Any number of files of any size; uploads from other devices resume after a dropped connection.
- **Local.** Indexing and search run on this PC. The backend accepts connections from this PC only; other devices on your network use the web app.

## Setup

Requirements: Windows 10/11, Python 3.12, Node.js 20+, an NVIDIA GPU with 6 GB or more (it also runs on CPU, slowly), Tesseract OCR (for Hindi text in images), and about 10 GB of free disk space for the AI models.

```bat
setup.bat
```

Setup creates the Python environment, installs the web app, writes `backend\.env` and `workspace\.env` (with a random shared `JWT_SECRET`), installs Hindi OCR data and downloads the AI models (about 7 GB, once).

**Choose a strong admin password** in `backend\.env` (`ADMIN_PASSWORD`) before the first start, or change it afterwards under Settings → Account. Anyone on your network who can open the web app can try to sign in.

## Accounts and sharing

There are two kinds of account:

- **Admin** – uploads and manages data, and creates accounts. The first admin comes from `ADMIN_EMAIL` / `ADMIN_PASSWORD` in `backend\.env`.
- **Demo admin** – every install (Windows and Linux) also gets the admin **`a@g.com` / `123456`**, created at startup if missing. Turn it off by setting `DEMO_ADMIN_EMAIL=` (empty) in `backend\.env` (`/etc/smartfinder/backend.env` on Linux) and deleting the account under **Users**.
- **User** – can only search and read the libraries an admin has shared with them. Users cannot upload, delete or see server paths.

Admins open **Users** in the sidebar to create user or admin accounts, reset passwords, and tick the libraries each user may search. A new user sees nothing until a library is shared with them. People and chat context follow the same rule. The old pre-library index belongs to no library, so only admins can search it.

To let someone create an admin account from the sign-in page, set `ADMIN_SETUP_CODE` in `backend\.env` (`setup.bat` generates one on a fresh install and prints it once). They enter it on **Create an admin account**. Leave it empty to turn that off.

## Running

```bat
run.bat          REM development mode
run.bat prod     REM production build: much faster, use this for other devices
```

- On this PC: <http://localhost:3000>
- Other devices on your network: `http://<this PC's address>:3000` (run.bat prints it)
- The backend (`127.0.0.1:8000`) is reachable from this PC only; the web app forwards requests to it.

## Linux (.deb)

Build the package on any machine with Python and git (Windows works; nothing else is needed, takes about a second):

```bat
python packaging\build_deb.py            REM -> dist\smartfinder_<version>_amd64.deb
```

On the Linux machine (Ubuntu 22.04+ or Debian 12, x86-64; NVIDIA driver 550+ for the GPU):

```bash
sudo apt install ./smartfinder_0.0.3_amd64.deb   # seconds: code, services, smartfinder-ctl
sudo smartfinder-ctl setup                       # downloads ~20 GB once, builds, starts
```

`setup` gets the code from GitHub (`GIT_REPO_URL` in `/etc/smartfinder/smartfinder.conf`, falling back to the copy in the package), installs Python 3.12 + packages with uv and Node.js 22 into `/opt/smartfinder`, builds the web app, downloads the models into `/var/lib/smartfinder/models`, prints a one-time admin password and starts the services. It can be re-run at any time; finished parts are skipped. Smart Finder runs as the account that installed it (`set-user` changes it), so it can index that account's folders and drives.

**Code updates come from GitHub; no new package needed.** Push to the repository, then:

```bash
smartfinder-ctl update-code --check   # incoming commits and what would be rebuilt
sudo smartfinder-ctl update-code      # pull, rebuild only what changed, restart; rolls back by itself on failure
sudo smartfinder-ctl rollback         # back to the code before the last update
```

Backend-only changes just restart the backend; web app changes rebuild it (~1 min); changes to `requirements.txt`, `package-lock.json` or `scripts/prefetch_models.py` install the new packages or models. `smartfinder-ctl` itself also updates this way. A new `.deb` is only needed when the apt dependencies or the systemd unit files in `packaging/linux/` change.

| Command | |
| --- | --- |
| `smartfinder-ctl status` | services, ports, health, GPU, code version, indexed files |
| `smartfinder-ctl files [--json]` | indexed / queued / failed files per library |
| `sudo smartfinder-ctl start\|stop\|restart [backend\|frontend]` | |
| `smartfinder-ctl logs [backend\|frontend] [-f]` | service logs (journald) |
| `sudo smartfinder-ctl set-port frontend 8080` | web app port (`set-port backend N` rebuilds the web app) |
| `sudo smartfinder-ctl config` | edit `/etc/smartfinder/backend.env` (Groq key, models, OCR) |
| `sudo smartfinder-ctl set-user <user>` / `set-repo <url> [branch]` / `models` | |

Files: code in `/opt/smartfinder/app` (git checkout), settings in `/etc/smartfinder`, database, uploads and models in `/var/lib/smartfinder`. `sudo apt remove smartfinder` removes the program and its environments; `sudo apt purge smartfinder` also deletes settings, the index database, uploads and models. The `.smartfind` folders inside your own folders are never touched.

## Libraries

Open **Libraries & Uploads** in the sidebar.

- **Add folder** opens the Windows folder picker (on this PC) or an in-app folder browser (from other devices). The folder is scanned and indexed in the background, then watched: new, changed, renamed and deleted files are picked up automatically.
- **Add files** indexes single files where they are (the *Linked files* library).
- **Upload** sends files or whole folders from any device into the *Uploads* library (`backend\data\uploads-library`), in resumable 8 MB chunks with no size limit. A file that is already indexed is not sent again.
- A folder on a USB or network drive goes offline when the drive is disconnected and comes back by itself, even under a new drive letter.
- **Remove from library** and **Stop indexing** never delete your files. Only files the app itself stored (uploads, internet imports) are deleted when you delete them.

Indexing runs in this order: text and pictures first (everything becomes searchable), then speech transcription, picture descriptions and sound analysis. Uploads always go first. Progress is shown at the top of the Libraries page.

## Searching

Type words, attach a file, or record with the microphone.

| You give | It finds |
| --- | --- |
| Words or a question | Passages by keyword and by meaning, in any language (an English query finds Hindi speech) |
| A description ("man in a white kurta", "photo of a crowd") | Photos and video frames, by appearance and by their generated descriptions |
| A photo | The same and similar pictures, and the people in it |
| A photo + words ("this person at the beach") | Only media with that person, ranked by the words |
| A person's name (after naming them on the People page) | Every photo and video moment with that person |
| A voice note or audio clip | What was said, and similar sounds |
| A sound ("dog barking", "applause") | The moment in audio and video files where it happens |
| A document | Files about the same thing |

Filters in the search box or under it: `kind:video`, `type:pdf`, `in:"Library name"`, `folder:trips/goa`, `after:2023-01-01`, `before:2024`, `year:2022`, and `"exact phrases"`.

Results open at the matching page or moment, with the matching frames shown for videos.

**Microphone:** browsers allow it only on this PC (`localhost`) or over HTTPS. From other devices, attach an audio file instead.

## People

The **People** page groups faces found in photos, videos and documents by person, across all libraries. Name someone once and search for them by name everywhere. Merge two groups that are the same person; hide people you don't want listed. Groups update automatically after indexing.

## How it works

- **Backend** (`backend/`): FastAPI. Each library has an SQLite index (`.smartfind/index.db`) with full-text search and float16 embeddings, plus FAISS vector indexes that switch to compressed IVF-PQ above 200,000 vectors.
- **Search**: keyword (BM25), meaning (Qwen3-Embedding-0.6B), pictures (Qwen3-VL-Embedding-2B, also picture + words as one query), faces (InsightFace buffalo_l), sounds (CLAP), file names and near-duplicate images are searched in parallel across all libraries, combined by reciprocal-rank fusion and re-scored by Qwen3-Reranker-0.6B; on GPUs with 12 GB or more, Qwen3-VL-Reranker-2B also re-judges the best picture matches (`VISUAL_RERANK` in `backend/.env`: `auto`, `on` or `off`). When the picture model changes, each library re-makes its picture vectors in the background ("updating image search") without indexing the files again.
- **Indexing**: PDF/Office/text/spreadsheet extraction, PaddleOCR PP-OCRv6 for scans and text in images (Tesseract re-reads Hindi lines), video keyframes, Whisper large-v3 transcription, Florence-2 picture descriptions, CLAP sound embeddings, face detection and grouping. Models share the GPU through a VRAM budget: indexing-only models wait in system RAM between uses.
- **Web app** (`workspace/`): Next.js.

## Moving an older knowledge base

Installations from before folder libraries stored copies in `backend\data\uploads`. To move them into the Uploads library and re-index them with the current models:

```bat
cd backend
venv\Scripts\python.exe scripts\migrate_legacy.py                 REM dry run: shows what would happen
venv\Scripts\python.exe scripts\migrate_legacy.py --apply --index  REM copy in and index now
```

Old source ids keep working (chats, links); duplicates become aliases; internet imports become Markdown files under `Uploads\Internet`. `--apply` deletes nothing and writes a manifest that `--rollback` uses to undo it. Once you have checked the results, `--finalize MANIFEST --yes` removes the old copies and old index entries.

## Checking search quality

```bat
cd backend
venv\Scripts\python.exe eval\run_eval.py
```

Runs the labelled queries in `backend\eval\queries.json` against your libraries and reports Recall@5 and MRR. Add queries for your own files and re-run after changes.

`eval\run_visual_eval.py` does the same for the picture model alone (`backend\eval\visual_queries.json`): each query is matched against image vectors only, without captions, OCR or keywords.

## Tests

```bat
cd backend
venv\Scripts\python.exe -m pytest
```

The tests use temporary folders and stand-in models; they never touch your data.

## Troubleshooting

- **Model downloads stall:** run `backend\scripts\prefetch_models.py` again (it uses plain HTTPS). Set `HF_HOME` in `backend\.env` to keep the models on another drive.
- **"Folder is not available":** the drive is disconnected or the folder was moved; reconnect it, or add the folder again at its new location (the existing index is reused).
- **Slow indexing on a 6 GB GPU while searching:** searches take priority; indexing pauses between batches and catches up afterwards.
