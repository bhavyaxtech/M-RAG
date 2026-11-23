# M-RAG Hardware Datasheet Evaluation

## Setup

This evaluation compares multimodal RAG with a text-only baseline on 18 hand-written hardware-datasheet questions covering ESP32-WROOM-32E/32UE, LM317, STM32F103C8, ATmega328P, and RP2040. Thirteen questions require a value or mapping found in a figure or table; five are prose controls.

Both methods use the same text extraction, 300–500-token chunking, `text-embedding-3-large` embedding pass, normalized vectors, exact FAISS `IndexFlatIP` retrieval, top-k of 5, and `gpt-5.6-sol` answer generation. The text-only index contains the same text vectors as the M-RAG index and differs only by excluding visual-caption vectors. For M-RAG, every retrieved visual's original crop is attached to the single generation call.

Each of the 36 method/question runs was graded manually. `retrieval_hit` records whether top-k contained valid ground-truth evidence; `answer_score` independently records `correct`, `partially correct`, `incorrect`, or `no answer`. Accuracy below counts only `correct` answers.

## Results

| Question split | Method | Questions | Retrieval hits | Hit rate | Correct answers | Accuracy |
|---|---|---:|---:|---:|---:|---:|
| Visual-required | M-RAG | 13 | 8 | 61.5% | 8 | 61.5% |
| Visual-required | Text-only | 13 | 0 | 0.0% | 0 | 0.0% |
| Prose controls | M-RAG | 5 | 4 | 80.0% | 4 | 80.0% |
| Prose controls | Text-only | 5 | 4 | 80.0% | 4 | 80.0% |
| **All questions** | **M-RAG** | **18** | **12** | **66.7%** | **12** | **66.7%** |
| **All questions** | **Text-only** | **18** | **4** | **22.2%** | **4** | **22.2%** |

Answer-score distribution:

| Question split | Method | Correct | Partially correct | Incorrect | No answer |
|---|---|---:|---:|---:|---:|
| Visual-required | M-RAG | 8 | 0 | 1 | 4 |
| Visual-required | Text-only | 0 | 1 | 1 | 11 |
| Prose controls | M-RAG | 4 | 0 | 0 | 1 |
| Prose controls | Text-only | 4 | 0 | 0 | 1 |

## Interpretation

The multimodal index produced a **61.5 percentage-point gain** in both retrieval hit rate and answer accuracy on visual-required questions. It correctly answered pin mappings, package assignments, thermal resistance, ADC conversion timing, pull-up resistance, and SPI timing values that the text-only index could not retrieve completely. The equal 80.0% result on prose controls indicates that adding visual evidence did not reduce performance on ordinary text questions in this sample.

The result also exposes the current bottleneck: multimodal retrieval missed 5 of 13 visual sources. Misses included two ESP32 electrical values and two RP2040 limits/timing values, showing that caption quality and table-fragment retrieval still need improvement. The LM317 line-regulation question was also answered incorrectly after the correct table failed to enter top-k. On the one text-only partial answer, prose supplied the 1 µs minimum STM32 ADC conversion time but not the table's 18 µs maximum.

These numbers validate the pipeline within one hardware-datasheet domain; they do not establish the cross-domain claim from the broader project pitch. The complete row-level generated answers and independent manual judgments are preserved in `eval/results.csv`. Exact deployments and index construction details are logged in `index/run_metadata.json`.
