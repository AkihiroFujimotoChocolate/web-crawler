# web-crawler
Asynchronous crawler for extracting text content from web pages.

- Async with `aiohttp` + `asyncio`
- Depth-limited recursion
- Optional URL filtering (regex)
- Optional “since” filtering via HTTP `Last-Modified`
- Pluggable callbacks (`data_handler`, `stop_handler`)

---

## Requirements

- Python: 3.11+ (tested on 3.13)
- Dependencies (capped below the next major per PEP 440 intent):
  - `aiohttp>=3.9,<4`
  - `beautifulsoup4>=4.12,<5`

Install:
```shell
pip install -r requirements.txt
```

--

## How to Run on Windows

1) Create a Python 3.13 virtual environment in the project root
```powershell
python3.13 -m venv .venv
```

2) Activate the virtual environment
```powershell
.venv\Scripts\Activate.ps1
```

3) Install dependencies
```powershell
pip install -r requirements.txt
```

4) Run the sample script
```powershell
python scrape_test.py
```

---

## How to Run on Linux

1) Create a Python 3.13 virtual environment in the project root
```shell
python3.13 -m venv .venv
```

2) Activate the virtual environment
```shell
source .venv/bin/activate
```

3) Install dependencies
```shell
pip install -r requirements.txt
```

4) Run the sample script
```shell
python scrape_test.py
```