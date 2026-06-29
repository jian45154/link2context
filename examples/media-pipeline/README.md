# Link2Context Media Pipeline Demo

This folder is a deterministic OCR/ASR handoff demo. It uses `fake_ocr.py`
instead of a real OCR engine so the queue and verification flow can be tested
without network access or platform cookies.

Recommended output folder:

```powershell
outputs/media-pipeline-demo
```

Flow covered by the regression test:

```text
media-pipeline
queue
export agent handoff
run-auto-queue --write-next
verify-auto-queue-next
run-media-text --apply --reindex
verify-media-text --require-reindex
```

For real runs, replace `fake_ocr.py` with a production OCR/ASR command such as
Tesseract, Sona, Vibe, or another local recognizer that writes recognized text
to stdout. See `docs/media-ocr-asr.md` for copyable image OCR and video/audio
ASR examples.
