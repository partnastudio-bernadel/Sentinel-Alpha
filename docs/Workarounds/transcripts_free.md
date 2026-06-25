# Transcript Pulling Alternatives & Fallbacks

This document outlines robust, cost-free methods for pulling corporate earnings transcripts and SEC filings as fallbacks for premium API providers like Financial Modeling Prep (FMP).

---

## 1. Motley Fool Scraping

The Motley Fool publishes full text transcripts of quarterly corporate earnings calls for thousands of publicly traded companies. This data is available for free on their website.

### Scraping Architecture
*   **Search Discovery**: Query Google, DuckDuckGo, or Motley Fool's internal search endpoint using the pattern: `{Ticker} earnings call transcript Motley Fool`.
*   **Parsing Strategy**: 
    *   Find the transition point for the **Q&A session** (usually marked by headers like `Questions and Answers` or `Q&A Session`).
    *   Extract management statements (Presentation block) and analyst/executive exchanges (Q&A block).
*   **User-Agent Compliance**: Always use a standard, descriptive User-Agent header to comply with their robot policies and avoid getting blocked.

---

## 2. Local Whisper Transcription (100% Free & Offline)

For companies that do not have their transcripts publicly indexed, the absolute fallback is to transcribe the audio of the earnings call directly using OpenAI's Whisper.

### Pipeline Setup
1.  **Locate Audio Source**: 
    *   Most companies upload the audio (`.mp3` or `.wav`) to their Investor Relations (IR) website after the call.
    *   Alternatively, community channels or financial analysts upload these calls to YouTube.
2.  **Download Audio**: Use `yt-dlp` to programmatically retrieve the audio file:
    ```bash
    yt-dlp -x --audio-format mp3 <YouTube_URL_or_IR_Audio_URL> -o transcript_audio.mp3
    ```
3.  **Local Transcription**: Use the open-source `faster-whisper` library to transcribe the file locally using your GPU or CPU for free:
    ```python
    from faster_whisper import WhisperModel

    model = WhisperModel("base", device="cuda", compute_type="float16")
    segments, info = model.transcribe("transcript_audio.mp3", beam_size=5)

    for segment in segments:
        print("[%.2fs -> %.2fs] %s" % (segment.start, segment.end, segment.text))
    ```

---

## 3. SEC EDGAR API (Free)

For official company filings (10-K, 10-Q), use the official SEC EDGAR REST API directly instead of commercial aggregators.

### Best Practices & Rules
*   **Rate Limits**: The SEC limits requests to **10 requests per second**. Exceeding this rate will trigger an immediate IP ban.
*   **User-Agent Headers**: You must declare a custom User-Agent identifying your application and contact email:
    ```python
    headers = {"User-Agent": "YourCompany Name (your.email@company.com)"}
    ```
*   **Parsing Tools**:
    *   Use `sec-parser` (Python) to convert the raw SEC HTML filings into clean semantic blocks.
    *   Target sections like **Item 1A** (Risk Factors) and **Item 7** (MD&A) by mapping the filing's Table of Contents or searching for item headers using regular expressions.
