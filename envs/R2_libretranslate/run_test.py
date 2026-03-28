"""
run_test.py — тест LibreTranslate (R2) на тестовом корпусе.

LibreTranslate — self-hosted REST API сервер поверх Argos Translate.
Запускает локальный HTTP-сервер, тестирует качество и накладные расходы API.

Запуск:
  envs/R2_libretranslate/venv/Scripts/python envs/R2_libretranslate/run_test.py

Сохраняет:
  results/R2_libretranslate/A_words.jsonl
  results/R2_libretranslate/B_sentences.jsonl
  results/R2_libretranslate/C_paragraphs.jsonl
  results/R2_libretranslate/D_document_translated.txt
  results/R2_libretranslate/summary.json
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Пути — ARGOS_PACKAGES_DIR на ASCII-путь (фикс кириллицы в имени польз-ля)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ARGOS_DATA = REPO_ROOT / ".argos_packages"
_ARGOS_DATA.mkdir(exist_ok=True)
os.environ["ARGOS_PACKAGES_DIR"] = str(_ARGOS_DATA)

CORPUS_BLOCKS = REPO_ROOT / "corpus" / "blocks"
CORPUS_DOCS   = REPO_ROOT / "corpus" / "documents"
RESULTS_DIR   = REPO_ROOT / "results" / "R2_libretranslate"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

LT_HOST = "127.0.0.1"
LT_PORT = 5001
LT_URL  = f"http://{LT_HOST}:{LT_PORT}"

VENV_PYTHON = Path(__file__).resolve().parent / "venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.exists():
    VENV_PYTHON = Path(__file__).resolve().parent / "venv" / "bin" / "python"


# ---------------------------------------------------------------------------
# RAM-монитор
# ---------------------------------------------------------------------------
class RamMonitor:
    def __init__(self):
        self.peak_mb = 0.0
        self._running = False
        self._thread = None

    def start(self):
        import psutil
        self._proc = psutil.Process(os.getpid())
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self):
        while self._running:
            try:
                rss = self._proc.memory_info().rss / 1024 / 1024
                self.peak_mb = max(self.peak_mb, rss)
            except Exception:
                pass
            time.sleep(0.05)


# ---------------------------------------------------------------------------
# Запуск LibreTranslate сервера
# ---------------------------------------------------------------------------
def start_server() -> subprocess.Popen:
    """Запускает libretranslate как подпроцесс с дрейном stdout в фоне."""
    env = {**os.environ, "ARGOS_PACKAGES_DIR": str(_ARGOS_DATA)}

    lt_exe = Path(__file__).resolve().parent / "venv" / "Scripts" / "libretranslate.exe"
    if not lt_exe.exists():
        lt_exe = Path(__file__).resolve().parent / "venv" / "bin" / "libretranslate"

    cmd = [
        str(lt_exe),
        "--host", LT_HOST,
        "--port", str(LT_PORT),
        "--load-only", "en,ru",
        "--disable-web-ui",
    ]

    log_path = RESULTS_DIR / "server.log"
    print(f"  Starting server: {' '.join(cmd)}")
    print(f"  Server log: {log_path}")

    log_file = open(log_path, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=log_file,
        env=env,
    )
    # Держим ссылку на лог, чтобы закрыть при завершении
    proc._log_file = log_file
    return proc


def wait_for_server(timeout: int = 180) -> bool:
    """Ждёт пока сервер не ответит на /languages."""
    import requests
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{LT_URL}/languages", timeout=3)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


# ---------------------------------------------------------------------------
# Перевод через REST API
# ---------------------------------------------------------------------------
def lt_translate(text: str, src: str, tgt: str) -> str:
    import requests
    r = requests.post(
        f"{LT_URL}/translate",
        json={"q": text, "source": src, "target": tgt, "format": "text"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["translatedText"]


# ---------------------------------------------------------------------------
# chrF2++ через sacrebleu
# ---------------------------------------------------------------------------
def chrf_score(hypothesis: str, reference: str) -> float:
    from sacrebleu.metrics import CHRF
    metric = CHRF(word_order=2)
    return metric.sentence_score(hypothesis, [reference]).score


# ---------------------------------------------------------------------------
# Тест одного блока
# ---------------------------------------------------------------------------
def test_block(jsonl_path: Path, block_name: str) -> dict:
    records = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    print(f"\n[{block_name}] {len(records)} items")

    results = []
    chrf_scores = []
    times_ms = []

    for rec in records:
        src_text = rec["source"]
        ref_text = rec["reference"]
        src_lang  = rec["src_lang"]
        tgt_lang  = rec["tgt_lang"]

        t0 = time.perf_counter()
        try:
            hyp = lt_translate(src_text, src_lang, tgt_lang)
            ok = True
        except Exception as e:
            hyp = f"[ERROR: {e}]"
            ok = False
        elapsed_ms = (time.perf_counter() - t0) * 1000

        score = chrf_score(hyp, ref_text) if ok else 0.0
        chrf_scores.append(score)
        times_ms.append(elapsed_ms)

        results.append({
            "id":         rec["id"],
            "src_lang":   src_lang,
            "tgt_lang":   tgt_lang,
            "source":     src_text,
            "hypothesis": hyp,
            "reference":  ref_text,
            "chrf":       round(score, 2),
            "time_ms":    round(elapsed_ms, 1),
        })

        if len(results) % 10 == 0:
            print(f"  {len(results)}/{len(records)}  chrF avg so far: "
                  f"{sum(chrf_scores)/len(chrf_scores):.1f}")

    out_path = RESULTS_DIR / f"{block_name}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = {
        "n":               len(results),
        "chrf_mean":       round(sum(chrf_scores) / len(chrf_scores), 2) if chrf_scores else 0,
        "chrf_min":        round(min(chrf_scores), 2) if chrf_scores else 0,
        "chrf_max":        round(max(chrf_scores), 2) if chrf_scores else 0,
        "time_total_ms":   round(sum(times_ms), 1),
        "time_per_item_ms": round(sum(times_ms) / len(times_ms), 1) if times_ms else 0,
    }
    print(f"  chrF mean={summary['chrf_mean']}  "
          f"total={summary['time_total_ms']:.0f}ms  "
          f"per_item={summary['time_per_item_ms']:.0f}ms")
    return summary


# ---------------------------------------------------------------------------
# Тест документа D
# ---------------------------------------------------------------------------
def test_document() -> dict:
    txt_path = CORPUS_DOCS / "test_doc.txt"
    if not txt_path.exists():
        print("\n[D_document] SKIP — test_doc.txt not found")
        return {}

    text = txt_path.read_text(encoding="utf-8")
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    print(f"\n[D_document] {len(paragraphs)} paragraphs, ~{len(text.split())} words")

    t0 = time.perf_counter()
    translated_parts = []
    errors = 0
    for i, para in enumerate(paragraphs):
        try:
            translated_parts.append(lt_translate(para, "en", "ru"))
        except Exception as e:
            translated_parts.append(f"[ERROR: {e}]")
            errors += 1
        if (i + 1) % 5 == 0:
            print(f"  {i+1}/{len(paragraphs)} paragraphs done")

    total_ms = (time.perf_counter() - t0) * 1000
    translated_text = "\n\n".join(translated_parts)

    out_path = RESULTS_DIR / "D_document_translated.txt"
    out_path.write_text(translated_text, encoding="utf-8")

    word_count = len(text.split())
    summary = {
        "paragraphs":     len(paragraphs),
        "word_count_src": word_count,
        "errors":         errors,
        "time_total_ms":  round(total_ms, 1),
        "words_per_sec":  round(word_count / (total_ms / 1000), 1) if total_ms > 0 else 0,
    }
    print(f"  done  time={total_ms/1000:.1f}s  speed={summary['words_per_sec']} words/s")
    return summary


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    import requests

    print("=" * 60)
    print("  R2 — LibreTranslate test")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    import libretranslate
    version = getattr(libretranslate, "__version__", "unknown")
    print(f"\nlibretranslate version: {version}")

    # Запуск сервера
    print(f"\n[server] Starting LibreTranslate on {LT_URL} ...")
    t_start = time.perf_counter()
    server_proc = start_server()

    ready = wait_for_server(timeout=240)
    startup_ms = (time.perf_counter() - t_start) * 1000

    if not ready:
        server_proc.terminate()
        server_proc._log_file.close()
        log_path = RESULTS_DIR / "server.log"
        log_tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        print(f"[ERROR] Server did not start in time.\nServer log (last 2000 chars):\n{log_tail}")
        sys.exit(1)

    print(f"  Server ready in {startup_ms/1000:.1f}s")

    # Проверяем доступные языки
    langs = requests.get(f"{LT_URL}/languages").json()
    lang_codes = [l["code"] for l in langs]
    print(f"  Available languages: {lang_codes}")

    # Прогрев
    print("\n[warmup] First request (model warm-up)...")
    ram = RamMonitor()
    ram.start()
    t_warmup = time.perf_counter()
    _ = lt_translate("Hello, world!", "en", "ru")
    _ = lt_translate("Привет, мир!", "ru", "en")
    warmup_ms = (time.perf_counter() - t_warmup) * 1000
    print(f"  warmup: {warmup_ms:.0f}ms")

    # Тесты
    block_results = {}
    block_results["A_words"]      = test_block(CORPUS_BLOCKS / "A_words.jsonl",      "A_words")
    block_results["B_sentences"]  = test_block(CORPUS_BLOCKS / "B_sentences.jsonl",  "B_sentences")
    block_results["C_paragraphs"] = test_block(CORPUS_BLOCKS / "C_paragraphs.jsonl", "C_paragraphs")
    block_results["D_document"]   = test_document()

    ram.stop()

    # Останавливаем сервер
    print("\n[server] Stopping...")
    server_proc.terminate()
    try:
        server_proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server_proc.kill()
    server_proc._log_file.close()

    # Итог
    chrf_values = [
        block_results[b]["chrf_mean"]
        for b in ["A_words", "B_sentences", "C_paragraphs"]
        if "chrf_mean" in block_results.get(b, {})
    ]
    overall_chrf = round(sum(chrf_values) / len(chrf_values), 2) if chrf_values else 0

    summary = {
        "model":        "LibreTranslate",
        "version":      version,
        "date":         datetime.now().strftime("%Y-%m-%d %H:%M"),
        "startup_ms":   round(startup_ms, 1),
        "warmup_ms":    round(warmup_ms, 1),
        "peak_ram_mb":  round(ram.peak_mb, 1),
        "blocks":       block_results,
        "overall_chrf": overall_chrf,
    }

    summary_path = RESULTS_DIR / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  Model:        LibreTranslate {version}")
    print(f"  Server start: {startup_ms/1000:.1f}s")
    print(f"  Warmup:       {warmup_ms:.0f}ms")
    print(f"  Peak RAM:     {ram.peak_mb:.0f} MB")
    print(f"  A words  :    chrF={block_results['A_words'].get('chrf_mean','?')}  "
          f"per_item={block_results['A_words'].get('time_per_item_ms','?')} ms")
    print(f"  B sentences:  chrF={block_results['B_sentences'].get('chrf_mean','?')}  "
          f"per_item={block_results['B_sentences'].get('time_per_item_ms','?')} ms")
    print(f"  C paragraphs: chrF={block_results['C_paragraphs'].get('chrf_mean','?')}  "
          f"per_item={block_results['C_paragraphs'].get('time_per_item_ms','?')} ms")
    if block_results.get("D_document"):
        d = block_results["D_document"]
        print(f"  D document:   {d.get('words_per_sec','?')} words/s  "
              f"time={d.get('time_total_ms',0)/1000:.1f}s")
    print(f"  Overall chrF (A+B+C avg): {overall_chrf}")
    print(f"\n  Results saved to: {RESULTS_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
