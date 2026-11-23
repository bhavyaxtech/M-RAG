# Real cross-document smoke test

**Scope:** two parsed documents from the 20-document collection. This is a live Azure run, not a hand-scored accuracy benchmark.

## Question
Compare AN2594 EEPROM emulation with AN2557 USART in-application programming: what is each used for, and how does each use the STM32F10xxx Flash memory? Cite both documents and distinguish data storage from firmware updates.

## Generated answer
| Document | What it is used for | How it uses STM32F10xxx embedded Flash |
|---|---|---|
| **AN2594 — EEPROM emulation** | Provides **non-volatile storage for application data** on STM32F10x devices that do not include EEPROM. It supports data updated at byte, half-word, or word granularity through software techniques. [S2] [S6] | Reserves Flash pages for data and manages them in software because Flash must be erased before space can be rewritten. For write-intensive use, pages can be rotated with wear leveling; AN2594 states that each on-chip Flash page can be programmed or erased reliably around 10,000 times. [S3] [S6] [S8] |
| **AN2557 — USART IAP** | Provides **firmware updating while the product is installed**. Its example IAP driver uses USART to download a new binary into internal Flash, upload an existing application image, or execute the loaded user program. [S1] [S7] | Places the approximately 12-Kbyte IAP program at Flash address `0x8000000`; its erase/program routines execute from Flash. The user firmware is placed separately starting at `0x8003000` in the documented implementation. [S4] |

Thus, **AN2594 treats part of Flash as an EEPROM-like store for persistent variables**, whereas **AN2557 reprograms Flash with complete firmware images over USART**. They can both write embedded Flash, but they solve different problems: routine data retention versus application firmware replacement. [S1] [S2] [S3] [S7]

For the AN2557 example, placement and available image size depend on density: medium-density and medium-density value-line implementations reserve pages 0–11 for IAP, while high-density, connectivity-line, XL-density, and high-density value-line implementations reserve pages 0–5; the remaining documented application capacities range from 116 Kbytes to 1012 Kbytes depending on the device group. [S4] AN2594 covers EEPROM emulation for STM32F10xxx low-, medium-, and high-density devices and connectivity-line devices as defined in that document. [S2]

## Retrieved evidence
| Citation | Document | Physical PDF page | Type |
|---|---|---:|---|
| [S1] | stm32-an2557 | 1 | text |
| [S2] | stm32-an2594 | 1 | text |
| [S3] | stm32-an2594 | 5 | text |
| [S4] | stm32-an2557 | 12 | table |
| [S5] | stm32-an2594 | 2 | text |
| [S6] | stm32-an2594 | 11 | text |
| [S7] | stm32-an2557 | 5 | text |
| [S8] | stm32-an2594 | 6 | text |

Both requested documents were retrieved and cited. Correctness has not been hand-scored. The full 20-document MinerU run is separate from this pilot.
