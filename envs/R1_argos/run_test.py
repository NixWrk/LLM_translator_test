"""
run_test.py — тест Argos Translate (R1) на тестовом корпусе.

Запуск:
  envs/R1_argos/venv/Scripts/python envs/R1_argos/run_test.py

Тестирует:
  - Блок A: 50 слов (EN->RU, RU->EN)
  - Блок B: 30 предложений
  - Блок C: 10 абзацев
  - Документ D: test_doc.txt (~3000 слов)

Сохраняет:
  results/R1_argos/A_words.jsonl
  results/R1_argos/B_sentences.jsonl
  results/R1_argos/C_paragraphs.jsonl
  results/R1_argos/D_document.txt
  results/R1_argos/summary.json
"""

import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Argos хранит языковые пакеты в %USERPROFILE%\.local\share\argos-translate\
# Если имя пользователя содержит кириллицу — SentencePiece (C++) не сможет
# открыть файл. Переопределяем на ASCII-путь внутри репозитория.
_ARGOS_DATA = REPO_ROOT / ".argos_packages"
_ARGOS_DATA.mkdir(exist_ok=True)
os.environ["ARGOS_PACKAGES_DIR"] = str(_ARGOS_DATA)
CORPUS_BLOCKS = REPO_ROOT / "corpus" / "blocks"
CORPUS_DOCS   = REPO_ROOT / "corpus" / "documents"
RESULTS_DIR   = REPO_ROOT / "results" / "R1_argos"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# RAM-монитор (фоновый поток)
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
# Установка языковых пакетов Argos
# ---------------------------------------------------------------------------
def ensure_language_packages():
    """Скачивает и устанавливает en<->ru пакеты если ещё нет."""
    print("[setup] Checking Argos language packages...")
    from argostranslate import package

    package.update_package_index()
    available = package.get_available_packages()
    installed = {(p.from_code, p.to_code) for p in package.get_installed_packages()}

    needed = [("en", "ru"), ("ru", "en")]
    for src, tgt in needed:
        if (src, tgt) in installed:
            print(f"  [ok] {src}->{tgt} already installed")
            continue
        pkgs = [p for p in available if p.from_code == src and p.to_code == tgt]
        if not pkgs:
            print(f"  [WARN] no package found for {src}->{tgt}")
            continue
        pkg = pkgs[0]
        print(f"  [download] {src}->{tgt}  version={pkg.package_version}  size~={getattr(pkg, 'size', '?')}")
        path = pkg.download()
        package.install_from_path(path)
        print(f"  [ok] {src}->{tgt} installed")


# ---------------------------------------------------------------------------
# Получить переводчик (кешируем объекты)
# ---------------------------------------------------------------------------
_translators: dict = {}

def get_translator(src: str, tgt: str):
    key = (src, tgt)
    if key not in _translators:
        from argostranslate import translate
        languages = translate.get_installed_languages()
        src_lang = next((l for l in languages if l.code == src), None)
        tgt_lang = next((l for l in languages if l.code == tgt), None)
        if src_lang is None or tgt_lang is None:
            raise RuntimeError(f"Language not installed: {src} or {tgt}")
        tr = src_lang.get_translation(tgt_lang)
        if tr is None:
            raise RuntimeError(f"No translation route {src}->{tgt}")
        _translators[key] = tr
    return _translators[key]


def argos_translate(text: str, src: str, tgt: str) -> str:
    return get_translator(src, tgt).translate(text)


# ---------------------------------------------------------------------------
# chrF2++ через sacrebleu
# ---------------------------------------------------------------------------
def chrf_score(hypothesis: str, reference: str) -> float:
    from sacrebleu.metrics import CHRF
    metric = CHRF(word_order=2)  # chrF2++
    return metric.sentence_score(hypothesis, [reference]).score


# ---------------------------------------------------------------------------
# Тест одного блока (A, B или C)
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
            hyp = argos_translate(src_text, src_lang, tgt_lang)
            ok = True
        except Exception as e:
            hyp = f"[ERROR: {e}]"
            ok = False
        elapsed_ms = (time.perf_counter() - t0) * 1000

        score = chrf_score(hyp, ref_text) if ok else 0.0
        chrf_scores.append(score)
        times_ms.append(elapsed_ms)

        results.append({
            "id":        rec["id"],
            "src_lang":  src_lang,
            "tgt_lang":  tgt_lang,
            "source":    src_text,
            "hypothesis": hyp,
            "reference": ref_text,
            "chrf":      round(score, 2),
            "time_ms":   round(elapsed_ms, 1),
        })

        # Краткий прогресс каждые 10 элементов
        if len(results) % 10 == 0:
            print(f"  {len(results)}/{len(records)}  chrF avg so far: "
                  f"{sum(chrf_scores)/len(chrf_scores):.1f}")

    # Сохраняем подробные результаты
    out_path = RESULTS_DIR / f"{block_name}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = {
        "n":              len(results),
        "chrf_mean":      round(sum(chrf_scores) / len(chrf_scores), 2) if chrf_scores else 0,
        "chrf_min":       round(min(chrf_scores), 2) if chrf_scores else 0,
        "chrf_max":       round(max(chrf_scores), 2) if chrf_scores else 0,
        "time_total_ms":  round(sum(times_ms), 1),
        "time_per_item_ms": round(sum(times_ms) / len(times_ms), 1) if times_ms else 0,
    }
    print(f"  chrF mean={summary['chrf_mean']}  "
          f"total={summary['time_total_ms']:.0f}ms  "
          f"per_item={summary['time_per_item_ms']:.0f}ms")
    return summary


# ---------------------------------------------------------------------------
# Тест документа D (test_doc.txt)
# ---------------------------------------------------------------------------
def test_document() -> dict:
    txt_path = CORPUS_DOCS / "test_doc.txt"
    if not txt_path.exists():
        print("\n[D_document] SKIP — test_doc.txt not found")
        return {}

    text = txt_path.read_text(encoding="utf-8")
    # Разбиваем на абзацы для перевода (Argos плохо работает с очень длинными текстами)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    print(f"\n[D_document] {len(paragraphs)} paragraphs, ~{len(text.split())} words")

    t0 = time.perf_counter()
    translated_parts = []
    errors = 0
    for i, para in enumerate(paragraphs):
        try:
            translated_parts.append(argos_translate(para, "en", "ru"))
        except Exception as e:
            translated_parts.append(f"[ERROR: {e}]")
            errors += 1
        if (i + 1) % 5 == 0:
            print(f"  {i+1}/{len(paragraphs)} paragraphs done")

    total_ms = (time.perf_counter() - t0) * 1000
    translated_text = "\n\n".join(translated_parts)

    # Сохраняем перевод
    out_path = RESULTS_DIR / "D_document_translated.txt"
    out_path.write_text(translated_text, encoding="utf-8")

    word_count = len(text.split())
    summary = {
        "paragraphs":      len(paragraphs),
        "word_count_src":  word_count,
        "errors":          errors,
        "time_total_ms":   round(total_ms, 1),
        "words_per_sec":   round(word_count / (total_ms / 1000), 1) if total_ms > 0 else 0,
    }
    print(f"  done  time={total_ms/1000:.1f}s  speed={summary['words_per_sec']} words/s")
    return summary


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("  R1 — Argos Translate test")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # Версия argostranslate
    import argostranslate
    version = getattr(argostranslate, "__version__", "unknown")
    print(f"\nargostranslate version: {version}")

    # Установка языковых пакетов
    ensure_language_packages()

    # Прогрев (первый вызов грузит модель)
    print("\n[warmup] First translation (model load)...")
    ram = RamMonitor()
    ram.start()
    t_warmup = time.perf_counter()
    _ = argos_translate("Hello, world!", "en", "ru")
    _ = argos_translate("Привет, мир!", "ru", "en")
    warmup_ms = (time.perf_counter() - t_warmup) * 1000
    print(f"  warmup: {warmup_ms:.0f}ms")

    # Тестируем блоки
    block_results = {}
    block_results["A_words"]      = test_block(CORPUS_BLOCKS / "A_words.jsonl",      "A_words")
    block_results["B_sentences"]  = test_block(CORPUS_BLOCKS / "B_sentences.jsonl",  "B_sentences")
    block_results["C_paragraphs"] = test_block(CORPUS_BLOCKS / "C_paragraphs.jsonl", "C_paragraphs")
    block_results["D_document"]   = test_document()

    ram.stop()

    # Итоговое summary
    chrf_values = [
        block_results[b]["chrf_mean"]
        for b in ["A_words", "B_sentences", "C_paragraphs"]
        if "chrf_mean" in block_results[b]
    ]
    overall_chrf = round(sum(chrf_values) / len(chrf_values), 2) if chrf_values else 0

    summary = {
        "model":          "Argos Translate",
        "version":        version,
        "date":           datetime.now().strftime("%Y-%m-%d %H:%M"),
        "warmup_ms":      round(warmup_ms, 1),
        "peak_ram_mb":    round(ram.peak_mb, 1),
        "blocks":         block_results,
        "overall_chrf":   overall_chrf,
    }

    summary_path = RESULTS_DIR / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  Model:       Argos Translate {version}")
    print(f"  Warmup:      {warmup_ms:.0f} ms")
    print(f"  Peak RAM:    {ram.peak_mb:.0f} MB")
    print(f"  A words  :   chrF={block_results['A_words'].get('chrf_mean','?')}  "
          f"per_item={block_results['A_words'].get('time_per_item_ms','?')} ms")
    print(f"  B sentences: chrF={block_results['B_sentences'].get('chrf_mean','?')}  "
          f"per_item={block_results['B_sentences'].get('time_per_item_ms','?')} ms")
    print(f"  C paragraphs:chrF={block_results['C_paragraphs'].get('chrf_mean','?')}  "
          f"per_item={block_results['C_paragraphs'].get('time_per_item_ms','?')} ms")
    if block_results.get("D_document"):
        d = block_results["D_document"]
        print(f"  D document:  {d.get('words_per_sec','?')} words/s  "
              f"time={d.get('time_total_ms',0)/1000:.1f}s")
    print(f"  Overall chrF (A+B+C avg): {overall_chrf}")
    print(f"\n  Results saved to: {RESULTS_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
