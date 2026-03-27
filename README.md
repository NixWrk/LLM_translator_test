# LightLocalTranslator

> Ветка `light-local-translator` — Трек 2 проекта [LLM Translator Test](../../tree/master)

Офлайн-переводчик для слабых ПК (CPU-only, 8–16 GB RAM) с обязательным сохранением форматирования документов.

Детальный план: [ПЛАН — LightLocalTranslator.md](ПЛАН%20—%20LightLocalTranslator.md)

---

## Стратегия

```
Фаза 1: готовые решения
    Argos → LibreTranslate → translateLocally → Okapi → TranslateGemma-Studio
        │
        ├─ Победитель найден? → берём как есть. СТОП.
        └─ Нет → Фаза 2: лёгкие модели напрямую (Python)
                    OPUS-MT → NLLB-600M → TranslateGemma 4B Q4 → MADLAD-3B
                        │
                        ├─ Победитель найден? → минимальная обвязка + GUI. СТОП.
                        └─ Нет → Фаза 3: собственная сборка с нуля
```

---

## Фаза 1 — Готовые решения (начинаем здесь)

| # | Решение | Установка | Качество | Форматирование |
|---|---------|-----------|----------|----------------|
| R1 | **Argos Translate** | `pip install argostranslate` | умеренное | нет |
| R2 | **LibreTranslate** | `pip install libretranslate` | умеренное | нет |
| R3 | **translateLocally (Bergamot)** | desktop app | умеренное | нет |
| R4 | **Document-Translation + Okapi** | Java + `git clone` | хорошее | **нативное** |
| R5 | **TranslateGemma-Studio** | `git clone` + GGUF | отличное | внешнее |
| R6 | **DesktopTranslator + M2M-100** | pip/exe + модель | хорошее | частичное |

> **Okapi тестируем в любом случае** — единственное готовое решение с нативным форматированием DOCX/ODT/HTML/PDF. Задаёт эталон даже если проиграет по качеству.

---

## Фаза 2 — Лёгкие модели (если Фаза 1 не дала победителя)

| # | Модель | Размер | RAM (CPU) | Runtime |
|---|--------|--------|-----------|---------|
| M1 | NLLB-200-distilled-600M | ~1.2 GB | ~1.5 GB | CTranslate2 |
| M2 | OPUS-MT ru-en / en-ru | ~300 MB | ~0.5 GB | CTranslate2 |
| M3 | TranslateGemma 4B Q4_K_M | ~2.5 GB | ~3–4 GB | llama-cpp-python |
| M4 | MADLAD-400-3B-MT | ~3 GB | ~3.5 GB | CTranslate2 int8 |
| M5 | M2M100-1.2B | ~5 GB | ~5.5 GB | CTranslate2 |

Порядок: M2 → M1 → M3 → M4 → M5 (от лёгкого к тяжёлому).

---

## Фаза 3 — Собственная сборка (только если Фазы 1–2 не дали результата)

```
LightLocalTranslator/
├── core/
│   ├── engine.py                  # translate(text, src, tgt)
│   ├── backends/
│   │   ├── ctranslate2_backend.py
│   │   └── llamacpp_backend.py
│   └── chunker.py
├── formats/
│   ├── txt_handler.py
│   ├── md_handler.py              # AST, защита кода/ссылок
│   ├── docx_handler.py            # python-docx, runs + стили
│   ├── pdf_handler.py             # PyMuPDF: redact + insert
│   └── xlsx_handler.py            # только строковые ячейки
├── gui/app.py                     # Gradio UI
└── translate.py                   # CLI
```

Сохранение форматирования:

| Формат | Что сохраняется |
|--------|----------------|
| TXT | пустые строки, отступы |
| MD | заголовки, списки, код (не переводится), ссылки, таблицы |
| DOCX | bold/italic/font/size, таблицы, колонтитулы, стили |
| PDF | координаты блоков, searchable |
| XLSX | стили, формулы и числа не трогаем |

---

## Тестовый корпус

```
corpus/
├── blocks/
│   ├── A_words.jsonl         # 50 слов + референс
│   ├── B_sentences.jsonl     # 30 предложений + референс
│   └── C_paragraphs.jsonl    # 10 абзацев ~200 слов + референс
└── documents/
    ├── test_doc.txt
    ├── test_doc.md            # заголовки, список, блок кода
    ├── test_doc.docx          # таблица, форматирование, колонтитулы
    ├── test_doc.pdf           # searchable
    └── test_doc.xlsx          # текст + формулы
```

---

## Последовательность работ

```
Этап 0  Подготовка: pip install (Фаза 1), тестовый корпус
Этап 1  Готовые решения (R1–R6) → есть победитель?
Этап 2  Лёгкие модели (M1–M5) → есть победитель?
Этап 3  Обработчики форматов: txt → md → docx → pdf → xlsx
Этап 4  Core engine + Chunker + GUI (Gradio)
Этап 5  Интеграционный тест всех форматов
Этап 6  Упаковка + УСТАНОВКА.md
```

---

## Что нужно установить

```bash
# Этап 0 — Фаза 1:
pip install argostranslate libretranslate
# Java JDK 11+ — вручную (для Okapi)
# git clone https://github.com/kukas/document-translation

# Этап 0 — Фаза 2 (если дойдём):
pip install ctranslate2 sentencepiece sacrebleu python-docx llama-cpp-python
```
