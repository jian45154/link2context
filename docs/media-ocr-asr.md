# Media OCR And ASR Workflows

Link2Context does not bundle an OCR or ASR engine. It prepares deterministic queues, runs explicit local commands when requested, and verifies result files before applying recognized text to the SQLite store.

This keeps media processing local, reviewable, and replaceable.

## Safe Default Flow

Start with an imported store:

```powershell
python -m link2context --html examples/xiaohongshu_media_heavy.html --url "https://www.xiaohongshu.com/explore/media-heavy" --platform xiaohongshu --out outputs/xhs-media-heavy
python -m link2context.store --db data/link2context.db ingest outputs/xhs-media-heavy
```

Inspect the pipeline:

```powershell
python -m link2context.store --db data/link2context.db media-pipeline
python -m link2context.store --db data/link2context.db media
python -m link2context.store --db data/link2context.db queue --format jsonl
```

If media only has remote URLs, cache it first:

```powershell
python -m link2context.store --db data/link2context.db cache-media --kind image --out-dir outputs/media-cache
python -m link2context.store --db data/link2context.db cache-media --kind video --out-dir outputs/media-cache
```

`run-media-text` uses `input_path` when local media exists and falls back to `input_url` when it does not.

## CI-Friendly Fake OCR/ASR

The deterministic fixture under `examples/media-pipeline/` uses a fake recognizer so tests can exercise the handoff flow without network access, models, platform cookies, or real media files.

```powershell
$fake = (Resolve-Path examples/media-pipeline/fake_ocr.py)
python -m link2context.store --db data/link2context.db run-media-text --kind image --out outputs/fake-ocr.jsonl --command-template "python `"$fake`" {input_source}" --model fake-ocr --language zh --confidence 0.90 --apply --reindex
python -m link2context.store --db data/link2context.db verify-media-text outputs/fake-ocr.jsonl --require-reindex
```

The same command-template pattern works for ASR tools that write transcript text to stdout.

## Image OCR With Tesseract

Tesseract is available as a preset. Link2Context does not install Tesseract; install it locally and make sure `tesseract` is on `PATH`.

Inspect preset readiness:

```powershell
python -m link2context.store --db data/link2context.db media-text-presets --format markdown
```

Run OCR over image queue items:

```powershell
python -m link2context.store --db data/link2context.db run-media-text --kind image --out outputs/ocr-results.jsonl --preset tesseract --language chi_sim+eng --apply --reindex
python -m link2context.store --db data/link2context.db verify-media-text outputs/ocr-results.jsonl --require-reindex
```

For a different OCR engine, provide a command template. The external command must print recognized text to stdout:

```powershell
python -m link2context.store --db data/link2context.db run-media-text --kind image --out outputs/ocr-results.jsonl --command-template "your-ocr-command --input {input_source}" --model your-ocr --language zh --confidence 0.85 --apply --reindex
```

Useful template fields include `{input_source}`, `{input_path}`, `{input_url}`, `{document_id}`, `{media_index}`, `{kind}`, and `{document_title}`.

## Video Or Audio ASR With Sona/Vibe

Sona and Vibe are available as presets for local whisper.cpp-style transcription. Link2Context does not bundle Sona, Vibe, Whisper models, or media files.

Inspect model and executable readiness:

```powershell
python -m link2context.store --db data/link2context.db media-text-presets --preset-model models/ggml-small.bin --tool-path C:\Tools\sona.exe --format markdown
python -m link2context.store --db data/link2context.db media-text-presets --preset-model models/ggml-small.bin --tool-path C:\Tools\vibe.exe --format markdown
```

Run ASR over video queue items:

```powershell
python -m link2context.store --db data/link2context.db run-media-text --kind video --out outputs/asr-results.jsonl --preset sona --preset-model models/ggml-small.bin --tool-path C:\Tools\sona.exe --language zh --apply --reindex
python -m link2context.store --db data/link2context.db run-media-text --kind video --out outputs/vibe-asr-results.jsonl --preset vibe --preset-model models/ggml-small.bin --tool-path C:\Tools\vibe.exe --language zh --apply --reindex
python -m link2context.store --db data/link2context.db verify-media-text outputs/asr-results.jsonl --require-reindex
```

For another ASR engine:

```powershell
python -m link2context.store --db data/link2context.db run-media-text --kind video --out outputs/asr-results.jsonl --command-template "your-asr-command --input {input_source}" --model your-asr --language zh --confidence 0.85 --apply --reindex
```

## Review Low Confidence Text

Low-confidence media text remains visible for review:

```powershell
python -m link2context.store --db data/link2context.db queue --low-confidence --format jsonl
python -m link2context.store --db data/link2context.db media
python -m link2context.store --db data/link2context.db actions
```

Re-run OCR/ASR or edit a result JSONL, then apply and verify:

```powershell
python -m link2context.store --db data/link2context.db apply-media-text outputs/ocr-review.jsonl --reindex
python -m link2context.store --db data/link2context.db verify-media-text outputs/ocr-review.jsonl --require-reindex
```

## Rules For Public Examples

- Do not commit model files, downloaded media, local databases, cookies, or private exports.
- Keep example commands explicit; commands that execute local tools should be reviewed before use.
- Prefer `examples/media-pipeline/fake_ocr.py` for CI and documentation tests.
- Use `outputs/`, `data/`, and `models/` for local generated artifacts; these are ignored by git.
