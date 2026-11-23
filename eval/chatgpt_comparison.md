# ChatGPT (chatgpt.com) head-to-head

Ran on: __________  |  ChatGPT model/plan: __________  |  Grader: Abhilash

## Why this exists

A panelist can upload the same datasheet to chatgpt.com and ask the same question.
This file records what actually happens when they do, graded by the same rubric as
`eval/results.csv`, so the comparison is a number instead of an ambush.

This is **not** the controlled experiment. `eval/RESULTS.md` is. There, M-RAG and
text-only differ by exactly one variable (visual vectors) on an identical codepath,
which is what licenses a causal claim. chatgpt.com is a closed retrieval stack with
unknown chunking, unknown figure handling, and a model that changes without notice,
so a win or loss here explains nothing about *which component* caused it. It is a
product comparison, and it is reported as one.

## Protocol

Follow this exactly, and write down where you deviated.

1. **Fresh chat per question.** Not per document, per question. Asking all of an
   ATmega batch in one thread lets earlier retrievals leak into later answers and
   inflates the score. Re-upload the PDF each time.
2. **Upload only the single relevant PDF** named in the `doc` column. This is a
   deliberate handicap in ChatGPT's favour: our system retrieves across all five
   datasheets at once, theirs gets handed the right book. Say so out loud when
   presenting; the concession is what makes the rest credible.
3. **Paste the question verbatim.** No rephrasing, no hints, no follow-ups, no
   'are you sure'. First answer is the answer. If you would not get to retry with
   our system, they do not get to retry either.
4. **Grade with the same four labels** used in `results.csv`: `correct`,
   `partially correct`, `incorrect`, `no answer`. Same standard, no softer bar
   because it is the competitor and no harsher one either.
5. **Record `verifiable_source` separately from correctness.** Did the answer point
   to a specific page, table, or figure you could open and check? `yes` / `no` /
   `wrong` (it cited something, and the citation was wrong). This column is the
   point of the whole exercise, so do not skip it when the answer is right.
6. **Log failures as data.** Upload rejected, timeout, refusal, truncated read:
   write it in Notes and score `no answer`. Do not retry into a better result.

`atmega328p.pdf` is 32 MB. If it will not upload, that is a finding, not a problem
to work around.

## Summary (fill in after grading)

| Split | Method | Q | Correct | Accuracy | Verifiable source |
|---|---|---:|---:|---:|---:|
| Visual-required | M-RAG | 13 | 8 | 61.5% | 13/13 |
| Visual-required | Text-only | 13 | 0 | 0.0% | n/a |
| Visual-required | ChatGPT | 13 |  |  |  |
| Prose controls | M-RAG | 5 | 4 | 80.0% | 5/5 |
| Prose controls | Text-only | 5 | 4 | 80.0% | n/a |
| Prose controls | ChatGPT | 5 |  |  |  |
| **All** | **M-RAG** | **18** | **12** | **66.7%** | **18/18** |
| **All** | **Text-only** | **18** | **4** | **22.2%** | **n/a** |
| **All** | **ChatGPT** | **18** |  |  |  |

M-RAG's `verifiable_source` is 18/18 by construction: every turn renders the exact
cropped segments it retrieved, whether or not the answer was right. That column is
not a claim about accuracy, it is a claim about auditability, and it is the one
column a chat window structurally cannot fill.

## Scoreboard

| # | Doc | Vis | M-RAG | Text-only | ChatGPT | Src |
|---:|---|:--:|---|---|---|---|
| 1 | esp32-wroom-32e-32ue | Y | correct | no answer |  |  |
| 2 | esp32-wroom-32e-32ue | Y | no answer | no answer |  |  |
| 3 | esp32-wroom-32e-32ue | Y | no answer | no answer |  |  |
| 4 | lm317 | Y | correct | no answer |  |  |
| 5 | lm317 | Y | correct | no answer |  |  |
| 6 | lm317 | Y | incorrect | incorrect |  |  |
| 7 | stm32f103c8 | Y | correct | no answer |  |  |
| 8 | stm32f103c8 | Y | correct | partially correct |  |  |
| 9 | stm32f103c8 | Y | correct | no answer |  |  |
| 10 | atmega328p | Y | correct | no answer |  |  |
| 11 | atmega328p | Y | correct | no answer |  |  |
| 12 | rp2040 | Y | no answer | no answer |  |  |
| 13 | rp2040 | Y | no answer | no answer |  |  |
| 14 | esp32-wroom-32e-32ue | n | correct | correct |  |  |
| 15 | lm317 | n | correct | correct |  |  |
| 16 | stm32f103c8 | n | no answer | no answer |  |  |
| 17 | atmega328p | n | correct | correct |  |  |
| 18 | rp2040 | n | correct | correct |  |  |

## Per-question log

### Q1 — esp32-wroom-32e-32ue

> In the ESP32-WROOM-32E/32UE pin-definition table, which module pin is TXD0, and which GPIO/UART transmit function does it expose?

**Ground truth:** Module pin 35; GPIO1 / U0TXD.

**Ours:** M-RAG `correct` · text-only `no answer`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

### Q2 — esp32-wroom-32e-32ue

> What minimum current must the external power supply deliver under the ESP32-WROOM-32E/32UE recommended operating conditions?

**Ground truth:** 0.5 A minimum.

**Ours:** M-RAG `no answer` · text-only `no answer`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

### Q3 — esp32-wroom-32e-32ue

> What is the typical resistance of the ESP32-WROOM-32E/32UE internal pull-up resistor?

**Ground truth:** 45 kΩ.

**Ours:** M-RAG `no answer` · text-only `no answer`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

### Q4 — lm317

> For the LM317 TO-220 legacy, TO-263, and SOT-223 packages, which pin and tab assignment corresponds to OUTPUT?

**Ground truth:** Pin 2 and the tab (2, TAB) for all three packages.

**Ours:** M-RAG `correct` · text-only `no answer`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

### Q5 — lm317

> For the new-chip LM317 in the 4-pin DCY (SOT-223) package, what is the junction-to-board thermal resistance, RθJB?

**Ground truth:** 8.4 °C/W.

**Ours:** M-RAG `correct` · text-only `no answer`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

### Q6 — lm317

> Over the full operating temperature range, with 3 V ≤ (VIN − VOUT) ≤ 40 V, what are the LM317's typical and maximum line-regulation values?

**Ground truth:** 0.02 %/V typical and 0.07 %/V maximum.

**Ours:** M-RAG `incorrect` · text-only `incorrect`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

### Q7 — stm32f103c8

> In the STM32F103xx LQFP48 package, which physical pin is assigned to PA9?

**Ground truth:** Pin 30.

**Ours:** M-RAG `correct` · text-only `no answer`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

### Q8 — stm32f103c8

> At an ADC clock of 14 MHz, what minimum and maximum total conversion times, including sampling time, are specified for the STM32F103x8/xB?

**Ground truth:** 1 µs minimum and 18 µs maximum.

**Ours:** M-RAG `correct` · text-only `partially correct`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

### Q9 — stm32f103c8

> What minimum, typical, and maximum weak pull-up equivalent resistance values are specified for the STM32F103x8/xB?

**Ground truth:** 30 kΩ minimum, 40 kΩ typical, and 50 kΩ maximum.

**Ours:** M-RAG `correct` · text-only `no answer`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

### Q10 — atmega328p

> In the ATmega328P 28-pin PDIP pinout, which physical pin carries PD1/TXD?

**Ground truth:** Pin 3.

**Ours:** M-RAG `correct` · text-only `no answer`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

### Q11 — atmega328p

> What maximum SPI slave rise/fall time is specified for the ATmega328P?

**Ground truth:** 1600 ns.

**Ours:** M-RAG `correct` · text-only `no answer`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

### Q12 — rp2040

> What is the maximum total IOVDD current that may be sourced by all RP2040 GPIO and QSPI pins?

**Ground truth:** 50 mA.

**Ours:** M-RAG `no answer` · text-only `no answer`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

### Q13 — rp2040

> According to the RP2040 pin output timing table, what are the minimum and maximum delays from the flop to the GPIO12 pad?

**Ground truth:** Minimum 2.35 ns; maximum 7.04 ns.

**Ours:** M-RAG `no answer` · text-only `no answer`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

### Q14 — esp32-wroom-32e-32ue (prose control)

> How many UART interfaces does the ESP32 have?

**Ground truth:** Three UART interfaces.

**Ours:** M-RAG `correct` · text-only `correct`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

### Q15 — lm317 (prose control)

> How does the LM317 recover after an overload condition?

**Ground truth:** It automatically resets from the overload; its output remains reduced or alternates on and off until the overload is removed.

**Ours:** M-RAG `correct` · text-only `correct`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

### Q16 — stm32f103c8 (prose control)

> What does the STM32F103x8/xB DMA controller's circular-buffer management avoid when the controller reaches the end of the buffer?

**Ground truth:** It avoids generating an interrupt when the controller reaches the end of the buffer.

**Ours:** M-RAG `no answer` · text-only `no answer`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

### Q17 — atmega328p (prose control)

> In the ATmega328P ADC, what analog input levels correspond to the minimum and maximum digital values?

**Ground truth:** The minimum value represents GND, and the maximum value represents the voltage on the AREF pin minus 1 LSB.

**Ours:** M-RAG `correct` · text-only `correct`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

### Q18 — rp2040 (prose control)

> Why is the RP2040's internal SRAM physically partitioned into six banks?

**Ground truth:** To allow simultaneous parallel access from different masters.

**Ours:** M-RAG `correct` · text-only `correct`

**ChatGPT answer:**

```

```

**Score:** `` · **Verifiable source:** `` · **Notes:**

---

## What to say when it comes up

Fill this in once the numbers exist. Whatever they are, lead with them rather than
waiting to be asked. Having tested the competitor and reported it straight is worth
more than the score itself.
