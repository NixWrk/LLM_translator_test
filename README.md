# LLM Translator Test

Исследование и разработка локальных переводчиков на базе LLM и специализированных NMT-моделей.

Два параллельных трека:

| Трек | Цель | Железо | Ветка |
|------|------|--------|-------|
| **Бенчмарк** | Сравнить модели и стеки по качеству / скорости | RTX 4080, 16 GB VRAM | `master` |
| **LightLocalTranslator** | Офлайн-переводчик для слабых ПК без GPU | CPU-only, 8–16 GB RAM | `light-local-translator` |

---

## Зачем

Задача — найти лучший локальный переводчик (RU↔EN и другие пары), который:
- работает **полностью офлайн**
- **сохраняет форматирование** документов (PDF, DOCX, XLSX, MD, TXT)
- пригоден для **слабых ПК** (CPU-only, ≤16 GB RAM)
- не требует платных сервисов или сложной инфраструктуры

---

## Правила проекта

- Никакого стороннего ПО (Ollama, LM Studio и аналоги) без явного согласования
- `pip install` и `git clone` — разрешены
- Java — разрешена (нужна для Okapi Framework)
- Скачивание моделей — разрешено (подключаем к существующему или собственному коду)
- Форматирование документов **обязательно сохраняется** для всех форматов
- Если готовое решение побеждает → берём его как есть, без пересборки

---

## Трек 1 — Бенчмарк моделей (ветка `master`)

**Железо:** RTX 4080 (16 GB VRAM). Тяжёлые модели тестируются параллельно на отдельном ПК.

### Что тестируем

**Уровень A — Специализированные translation-модели**

| # | Модель | VRAM | Runtime |
|---|--------|------|---------|
| A1 | TranslateGemma 12B (Q4_K_M) | ~7 GB | llama.cpp |
| A2 | TranslateGemma 4B (Q4_K_M) | ~3 GB | llama.cpp |
| A3 | GemmaX2-28-9B (Q4_K_M) | ~5.5 GB | llama.cpp |
| A4 | NLLB-200-3.3B (fp16) | ~7 GB | HF Transformers |
| A5 | NLLB-200-distilled-600M | ~1.2 GB | CTranslate2 |
| A6 | MADLAD-400-10B-MT (int8) | ~6 GB | CTranslate2 |
| A7 | MADLAD-400-3B-MT (int8) | ~3 GB | CTranslate2 |

**Уровень B — Translation-tuned LLM**

| # | Модель | VRAM | Runtime |
|---|--------|------|---------|
| B1 | ALMA-R-13B (Q4_K_M) | ~8 GB | llama.cpp |
| B2 | TowerInstruct-Mistral-7B (Q4_K_M) | ~4.5 GB | llama.cpp |
| B3 | SeamlessM4T-v2-large | ~10 GB | HF Transformers |

**Уровень D — Лёгкие baseline**

| # | Модель | Размер | Runtime |
|---|--------|--------|---------|
| D1 | OPUS-MT ru-en / en-ru | ~300 MB | CTranslate2 |
| D2 | M2M100-1.2B | ~5 GB | CTranslate2 |
| D3 | mBART-50 large | ~2.4 GB | HF Transformers |

**Уровень E — Готовые end-to-end стеки**

| # | Стек | Приоритет |
|---|------|-----------|
| E1 | Local-Translator + Ollama + TranslateGemma 4B | ★★★ |
| E2 | TranslateGemma-Studio + llama.cpp | ★★★ |
| E3 | NLLB-600M + CTranslate2 pipeline | ★★★ |
| E4 | Document-Translation + Okapi + Marian | ★★ |
| E5 | Argos Translate | ★★ |
| E6 | LibreTranslate (self-hosted) | ★★ |

### Метрики бенчмарка

| Метрика | Инструмент |
|---------|-----------|
| chrF2++ | `sacrebleu` |
| BLEU | `sacrebleu` |
| COMET-22 | `unbabel-comet` |
| Скорость (токенов/сек) | замер в скрипте |
| RAM / VRAM пик | `psutil`, `nvidia-smi` |
| Субъективная оценка (1–5) | ручная по 20 примерам |

### Тестовый корпус бенчмарка

```
corpus/
├── words.jsonl           # 100 слов + 50 устойчивых выражений, EN↔RU
├── paragraphs.jsonl      # 70 абзацев (технические, научные, публицистика, юридика)
├── documents/            # 3 документа ~5000 слов (статья, руководство, худлит)
└── references.jsonl      # Эталонные переводы для метрик
```

### Последовательность работ (Трек 1)

```
Этап 0: инфраструктура → benchmark.py, evaluate.py, корпус
Этап 1: baseline → OPUS-MT, Argos, NLLB-600M
Этап 2: NMT-модели → NLLB-3.3B, MADLAD, M2M100
Этап 3: LLM-переводчики → TranslateGemma 4B/12B, GemmaX2, TowerInstruct, ALMA
Этап 4: готовые стеки → TranslateGemma-Studio, Local-Translator, Okapi
Этап 5: сводный анализ → таблицы, графики, РЕЗУЛЬТАТЫ.md
```

---

## Трек 2 — LightLocalTranslator (ветка `light-local-translator`)

Офлайн-переводчик для слабых ПК. Стратегия — **сначала проверить готовые решения**. Если одно побеждает — берём его как есть, не пересобираем.

### Дерево решений

```
Фаза 1: готовые решения
    Argos Translate → LibreTranslate → Document-Translation+Okapi
    → TranslateGemma-Studio (llama.cpp) → translateLocally
        │
        ├─ Победитель найден? → ЭТО И ЕСТЬ финальный LightLocalTranslator. СТОП.
        │
        └─ Нет → Фаза 2: лёгкие модели напрямую (Python)
                    OPUS-MT → NLLB-600M → TranslateGemma 4B Q4 → MADLAD-3B
                        │
                        ├─ Победитель найден? → Минимальная обвязка + GUI. СТОП.
                        │
                        └─ Нет → Фаза 3: собственная сборка с нуля
```

### Фаза 1 — Готовые решения

| # | Решение | Установка | Ожидаемое качество | Форматирование |
|---|---------|-----------|-------------------|----------------|
| R1 | **Argos Translate** | `pip install argostranslate` | умеренное | нет |
| R2 | **LibreTranslate** | `pip install libretranslate` | умеренное | нет |
| R3 | **translateLocally (Bergamot)** | desktop app | умеренное | нет |
| R4 | **Document-Translation + Okapi** | Java + `git clone` | хорошее | **нативное** |
| R5 | **TranslateGemma-Studio** | `git clone` + GGUF | отличное | внешнее |
| R6 | **DesktopTranslator + M2M-100** | pip/exe + модель | хорошее | частичное |

> **Okapi** тестируется в любом случае — это единственное готовое решение с нативным сохранением форматирования DOCX/ODT/HTML/PDF. Даже если проиграет по качеству — задаёт эталон форматирования.

### Фаза 2 — Лёгкие модели (только если Фаза 1 не дала победителя)

| # | Модель | Размер | RAM (CPU) | Runtime |
|---|--------|--------|-----------|---------|
| M1 | NLLB-200-distilled-600M | ~1.2 GB | ~1.5 GB | CTranslate2 |
| M2 | OPUS-MT ru-en / en-ru | ~300 MB | ~0.5 GB | CTranslate2 |
| M3 | TranslateGemma 4B Q4_K_M | ~2.5 GB | ~3–4 GB | llama-cpp-python |
| M4 | MADLAD-400-3B-MT | ~3 GB | ~3.5 GB | CTranslate2 int8 |
| M5 | M2M100-1.2B | ~5 GB | ~5.5 GB | CTranslate2 |

### Фаза 3 — Собственная сборка (только если Фазы 1–2 не дали результата)

Архитектура финального приложения:

```
LightLocalTranslator/
├── core/
│   ├── engine.py                  # абстрактный интерфейс translate(text, src, tgt)
│   ├── backends/
│   │   ├── ctranslate2_backend.py # NLLB, OPUS-MT, MADLAD
│   │   └── llamacpp_backend.py    # TranslateGemma GGUF
│   └── chunker.py                 # разбивка длинных текстов по предложениям
├── formats/
│   ├── txt_handler.py             # plain text
│   ├── md_handler.py              # Markdown (AST, защита кода/ссылок)
│   ├── docx_handler.py            # DOCX (python-docx, runs + стили)
│   ├── pdf_handler.py             # PDF (PyMuPDF: redact + insert)
│   └── xlsx_handler.py            # Excel (openpyxl, только строковые ячейки)
├── gui/
│   └── app.py                     # Gradio UI (текст + файл)
├── translate.py                   # CLI: --input file.docx --src en --tgt ru
└── config.py
```

### Сохранение форматирования (обязательное требование)

| Формат | Метод | Что сохраняется |
|--------|-------|----------------|
| **TXT** | разбивка по `\n\n` | пустые строки, отступы |
| **MD** | AST (markdown-it-py) | заголовки, списки, код, ссылки, таблицы |
| **DOCX** | python-docx (runs) | bold, italic, font, size, таблицы, колонтитулы |
| **PDF** | PyMuPDF (redact+insert) | координаты блоков, searchable |
| **XLSX** | openpyxl | стили, формулы (не трогаем), числа (не трогаем) |

### Тестовый корпус LightLocalTranslator

```
corpus/
├── blocks/
│   ├── A_words.jsonl         # 50 слов с референсным переводом
│   ├── B_sentences.jsonl     # 30 предложений с референсом
│   └── C_paragraphs.jsonl    # 10 абзацей ~200 слов с референсом
└── documents/
    ├── test_doc.txt          # ~3000 слов EN
    ├── test_doc.md           # тот же текст в Markdown
    ├── test_doc.docx         # с таблицей, форматированием, колонтитулами
    ├── test_doc.pdf          # searchable PDF
    └── test_doc.xlsx         # таблица: текст + формулы
```

Документ содержит: введение, технические термины, числа/формулы, таблицу, блок кода (в MD).

### Последовательность работ (Трек 2)

```
Этап 0: установить зависимости Фазы 1, подготовить тестовый корпус

Этап 1: Готовые решения
  R1: Argos Translate   → блоки A–C, замер скорости + RAM
  R2: LibreTranslate    → блоки A–C через REST API
  R3: translateLocally  → субъективная оценка, блоки A–B
  R4: Document-Translation + Okapi → DOCX и PDF round-trip, форматирование
  R5: TranslateGemma-Studio → блоки A–D включая документы
  → Оценить: есть победитель? → если да, СТОП

Этап 2: Лёгкие модели (если нужно)
  M2 (OPUS-MT) → M1 (NLLB-600M) → M3 (TranslateGemma 4B) → M4 (MADLAD-3B)
  → Выбрать лучшую, написать минимальный скрипт + GUI

Этап 3: Обработчики форматов (если нужно собирать своё)
  txt → md → docx → pdf → xlsx

Этап 4: Core engine + GUI (Gradio)

Этап 5: Интеграционный тест всех форматов

Этап 6: Упаковка + УСТАНОВКА.md для пользователя слабого ПК
```

---

## Что уже установлено (dev-машина)

| Пакет | Версия | Роль |
|-------|--------|------|
| `torch` + CUDA 12.6 | 2.11.0 | инференс HF-моделей на GPU |
| `transformers` | 4.57.6 | HF-модели |
| `accelerate` | 0.28.0 | ускорение трансформеров |
| `huggingface_hub` | 0.36.2 | скачивание моделей |
| `gradio` | 4.11.0 | веб-GUI |
| `customtkinter` | 5.2.2 | десктоп-GUI |
| `PyMuPDF` | 1.26.7 | PDF (чтение + запись) |
| `pdfminer.six` | 20260107 | извлечение текстовых блоков |
| `reportlab` | 4.4.7 | генерация PDF |
| `openpyxl` | 3.1.5 | XLSX |
| `markdown-it-py` | 3.0.0 | парсинг Markdown (AST) |
| `markdownify` | 1.2.2 | HTML → Markdown |
| `beautifulsoup4` | 4.13.3 | HTML парсинг |
| `psutil` | 6.0.0 | замер RAM |

## Что нужно доустановить

```bash
# Фаза 1 (готовые решения):
pip install argostranslate
pip install libretranslate
# Java JDK 11+ — вручную (для Okapi)
# git clone https://github.com/kukas/document-translation

# Фаза 2 (лёгкие модели, если дойдём):
pip install ctranslate2 sentencepiece sacrebleu
pip install python-docx
pip install llama-cpp-python
```

---

## Структура репозитория

```
LLM_translator_test/
│
├── README.md
│
├── # Исследование (оба трека)
├── Обзор translate моделей.md
├── Обзор по относительно готовым стекам.md
├── Решение для офлайн переводчика на слабом ПК.md
│
├── # Планы
├── ПЛАН 1 — Бенчмарк моделей и стеков.md      ← Трек 1
├── ПЛАН 2 — Лёгкий локальный переводчик.md     ← Трек 2 (обзор)
├── ПЛАН — LightLocalTranslator.md              ← Трек 2 (детальный план)
│
├── corpus/                  # тестовые тексты (создаётся в Этапе 0)
├── results/                 # результаты бенчмарков
└── LightLocalTranslator/    # код финального переводчика (Фаза 3, если дойдём)
```

---

## Ветки

| Ветка | Назначение |
|-------|-----------|
| `master` | исследование, планы, бенчмарк (Трек 1) |
| `light-local-translator` | разработка LightLocalTranslator (Трек 2) |
