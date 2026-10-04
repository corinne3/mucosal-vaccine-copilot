# Setup on Windows, CPU only, no credits

Written for exactly this configuration: a Windows laptop, no GPU, no paid AI credits,
intermittent network. Nothing here needs a GPU and nothing calls a paid API.

---

## 1. Python

Install Python 3.11 or 3.12 from [python.org](https://www.python.org/downloads/windows/)
(3.13 works too). **Tick "Add python.exe to PATH"** in the installer.

```powershell
python --version        # expect 3.10+
```

## 2. The project

```powershell
cd $HOME\Documents
git clone <your repo url> mucosal-vaccine-copilot
cd mucosal-vaccine-copilot

python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell refuses to run the activation script:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Then:

```powershell
pip install -e ".[all]"
```

If `pymupdf` fails to build (it rarely does on Windows, but it can), install everything
else — the PDF path is optional and the project detects its absence:

```powershell
pip install -e ".[app,agent,mcp,dev]"
```

## 3. Check

```powershell
python -m mvc.cli doctor
```

You want every package `OK`. `plotly` and `streamlit` missing means no dashboard;
everything else still runs.

```powershell
python -m mvc.cli demo
pytest -q
python -m mvc.eval.run
```

## 4. Ollama — optional, and genuinely optional

Download the Windows installer from [ollama.com](https://ollama.com). Then:

```powershell
ollama pull qwen2.5:3b         # ~2 GB, the text model
ollama pull nomic-embed-text   # ~270 MB, embeddings for retrieval
ollama pull qwen2.5vl:3b       # ~3 GB, vision, only for figure digitisation
```

Verify:

```powershell
ollama list
python -m mvc.cli doctor       # should now show the models as present
```

### Expectations on CPU

A 3B model on a laptop CPU runs at roughly 5–15 tokens per second. That is:

| Task | Rough time |
|---|---|
| Parse one scenario | 5–15 s |
| Extract from one abstract | 20–60 s |
| Extract from one full text | 2–5 min |
| Embed the whole evidence base (once, then cached) | 1–2 min |
| Read one figure with the vision model | 1–3 min |

Slow, not unusable — and the deterministic fallbacks exist precisely so you are never
waiting on a model during a demo.

### If RAM is tight

```powershell
$env:MVC_LLM_MODEL = "qwen2.5:1.5b"   # ~1 GB
```

Smaller models follow JSON schemas less reliably; the extractor catches that
(`ValueError` → silent fall back to rules).

### Pointing at different models

```powershell
$env:MVC_LLM_MODEL   = "llama3.2:3b"
$env:MVC_EMBED_MODEL = "all-minilm"
$env:MVC_VLM_MODEL   = "llava:7b"
$env:OLLAMA_HOST     = "http://localhost:11434"
```

Set them permanently in *System Properties → Environment Variables* if you prefer.

## 5. Before travelling

```powershell
python scripts\download_pack.py
```

This installs dependencies, builds an **offline pip wheelhouse** under `vendor/wheels`,
downloads the papers and trial registrations into `data\raw\`, pulls the Ollama models,
warms the embedding cache, then runs tests, evals and the demo as a final check.

With the wifi off afterwards:

```powershell
python -m mvc.cli doctor        # confirm the corpus is there
python -m mvc.cli demo          # works offline
python -m mvc.cli dashboard     # works offline
```

To reinstall packages with no network at all:

```powershell
pip install --no-index --find-links vendor\wheels -r requirements.txt
```

## 6. MCP server in Claude Desktop

Add to `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mucosal-vaccine-copilot": {
      "command": "C:\\Users\\<you>\\Documents\\mucosal-vaccine-copilot\\.venv\\Scripts\\python.exe",
      "args": ["-m", "mvc.mcp_server"],
      "cwd": "C:\\Users\\<you>\\Documents\\mucosal-vaccine-copilot"
    }
  }
}
```

Use the **absolute path to the venv's python.exe**, and double backslashes. Restart Claude
Desktop; ten tools should appear (`search_evidence`, `propose_strategy`,
`check_comparability`, `generate_roadmap`, …).

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: mvc` | venv not active, or not installed with `-e` | `.\.venv\Scripts\Activate.ps1` then `pip install -e .` |
| `streamlit: command not found` | extras not installed | `pip install "streamlit>=1.33"` |
| Dashboard opens blank | plotly missing | `pip install "plotly>=5.20"` |
| `Ollama not reachable` | service not running | launch the Ollama app, or `ollama serve` |
| Retrieval says "BM25 only" | embedding model absent | `ollama pull nomic-embed-text` (or ignore — recall@3 is 0.79 without it) |
| `import fitz` fails | PyMuPDF missing | `pip install pymupdf` — only the PDF path needs it |
| Download step gets HTTP errors | rate limiting | re-run; `fetch.py` retries with backoff and the manifest records what failed |
| Tests slow | bootstrap resampling | `pytest -q -x` while iterating; CI runs the full suite |

## 8. Day-to-day commands

```powershell
.\.venv\Scripts\Activate.ps1

python -m mvc.cli doctor
python -m mvc.cli demo
python -m mvc.cli dashboard
python -m mvc.cli propose "intranasal RSV vaccine in infants, 4 visits, 90 days" --print
python -m mvc.cli search "nasal IgA durability"
python -m mvc.cli graph
python -m mvc.cli roadmap
python -m mvc.eval.run
pytest -q
```
