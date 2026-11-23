# How to run the demo

You need to do three things. That's it.

---

## 1. Get the code

Open https://github.com/abhilashHQ/Multimodal-Rag and download it as a ZIP
(green **Code** button → **Download ZIP**), then right-click the ZIP → **Extract All**,
and extract it to a **short folder** such as `C:\Multimodal-Rag`. Some files sit deep
inside, and Windows drops them if the folder path is long (deep OneDrive folders are
the usual culprit).

Or, if you have Git installed:

```
git clone https://github.com/abhilashHQ/Multimodal-Rag.git C:\Multimodal-Rag
```

## 2. Install Python and Node.js (once)

- **Python 3.12** from https://www.python.org/downloads/. On the very first
  installer screen, tick **"Add python.exe to PATH"**.
- **Node.js LTS** from https://nodejs.org/, with the default options.

Restart the computer after installing both.

You also need a **ChatGPT account**. The demo uses it to write answers, so there
are no API keys or credits involved.

## 3. Double-click `run.bat`

A black window opens.

- **The first time**, it sets itself up. This takes 5 to 15 minutes depending on
  your internet, because it downloads a 2.3 GB search model. Just leave it alone.
- **Once during setup**, a browser window opens asking you to **sign in to ChatGPT**.
  Sign in, then go back to the black window.
- **Every time after that**, it checks itself and starts in under a minute.

Your browser opens automatically at **http://localhost:8000**.

**Leave the black window open during the whole demo.** Closing it turns the demo off.
When you're finished, close the window or press `Ctrl` + `C` in it.

Each answer takes 10 to 20 seconds and appears all at once.

> **Azure mode (optional).** If Abhilash sends you a `.env` file, save it in the
> folder next to `run.bat` before step 3 and the demo uses Azure instead. It must
> be named exactly `.env`, not `.env.txt`. Without it, `run.bat` creates one for
> the free setup described above.

---

# Running the demo for your teacher

Click a datasheet on the left, then ask it a question. Good ones to use:

| Document | Question |
|---|---|
| ESP32-WROOM-32E/32UE | Which module pin is TXD0 on the ESP32-WROOM-32E? |
| LM317 | What is the maximum continuous output current in the electrical characteristics table? |
| RP2040 / Raspberry Pi Pico | Which pins are used for SPI0? |
| ATmega328P | What is the maximum operating frequency at 5V? |

**The point to make:** the answer comes from a *picture* — a pinout diagram or a
dense table — not from the text of the PDF. Normal text search cannot find it.

Three things on screen prove it:

1. **The evidence panel on the right.** Each source is labelled `S1`, `S2`, `S3`…
   The ones tagged **FIGURE** or **TABLE** are images the system read.
2. **Click "View page N"** under any source. It opens that page of the real PDF
   with the exact region highlighted. That is where the answer came from.
3. **Click "Why this answer".** It shows how the question was routed, what was
   searched for, the relevance score, and which sources were actually used
   versus merely retrieved.
4. **Click "Build provenance"** at the bottom right. It lists the exact models
   and the index that produced the answer.

If it says it cannot answer from the document, that is intentional. The system
refuses to guess when the evidence does not support an answer.

---

# If something goes wrong

**The black window shows an error and closes / stays open with red text.**
Read the message. It tells you what to fix. If it mentions Python, install
Python 3.12 from https://www.python.org/downloads/ and **tick "Add python.exe to PATH"**
on the first installer screen.

**Browser says "can't reach this page".**
The server is probably still starting. Wait 20 seconds and refresh.

**Browser opens but the page is blank or shows an error banner.**
Check the black window is still open and has no error in it.

**It says Node.js is not installed.**
Install Node.js LTS from https://nodejs.org/, close the black window, and double-click
`run.bat` again.

**It says Codex is not signed in, or the sign-in window never opened.**
Open a Command Prompt, type `codex login`, press Enter, and sign in with ChatGPT.
Then double-click `run.bat` again.

**It says the Codex version is not compatible.**
Open a Command Prompt and run `npm install -g @openai/codex@latest`, then try again.

**It mentions a DLL, `torch`, or `c10.dll`.**
Install the Microsoft Visual C++ Redistributable from
https://aka.ms/vs/17/release/vc_redist.x64.exe, restart, and try again.

**Anything else:** take a photo of the black window and send it to Abhilash.
