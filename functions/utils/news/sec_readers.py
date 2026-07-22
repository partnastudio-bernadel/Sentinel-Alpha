import json
from functions.tools.edgar_tools import get_sec_10k_section
from functions.tools.transcript_tools import fetch_and_split_transcript
from functions.utils.common.sanitize import sanitize_for_prompt
from functions.constants import SEC_TEXT_MAX_CHARS

def execute_reading_workers(
    tickers_to_query: list,
    textual_inertia_agent,
    tension_extractor_agent,
    db = None
) -> dict:
    """Runs Unstructured Reading Workers (Textual Inertia and Q&A Tension) for target tickers."""
    import concurrent.futures
    print("\n[+] Step 2: Running Unstructured Reading Workers Layer...")
    indicators_report_data = {}
    
    def process_ticker(t_symbol):
        ticker_data = {
            "textual_inertia": None,
            "textual_inertia_reason": "No data available.",
            "tension": None,
            "tension_reason": "No data available."
        }
        print(f"[*] Analyzing qualitative indicators for asset: {t_symbol}...")
        
        # A. Item 1A (Risk Factors) Textual Inertia (Lazy Prices)
        current_year = 2024
        ti_res = fetch_textual_inertia_for_year(t_symbol, current_year, textual_inertia_agent, db=db)
        ticker_data["fiscal_year"] = current_year
        if ti_res.get("textual_inertia") is not None:
            ticker_data["textual_inertia"] = ti_res["textual_inertia"]
        ticker_data["textual_inertia_reason"] = ti_res["textual_inertia_reason"]

        # B. Analyst Q&A Tension Extractor
        current_quarter = 1
        qa_res = fetch_qa_tension_for_period(t_symbol, current_year, current_quarter, tension_extractor_agent, db=db)
        ticker_data["fiscal_quarter"] = current_quarter
        if qa_res.get("tension") is not None:
            ticker_data["tension"] = qa_res["tension"]
        ticker_data["tension_reason"] = qa_res["tension_reason"]
            
        return t_symbol, ticker_data

    workers_limit = min(5, len(tickers_to_query)) if tickers_to_query else 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers_limit) as executor:
        results = executor.map(process_ticker, tickers_to_query)
        for t_symbol, ticker_data in results:
            indicators_report_data[t_symbol] = ticker_data

    return indicators_report_data


def fetch_textual_inertia_for_year(
    t_symbol: str,
    target_year: int,
    textual_inertia_agent,
    db = None
) -> dict:
    """Computes Textual Inertia for a specific fiscal year (comparing target_year vs target_year - 1)."""
    import time
    prev_year = target_year - 1
    res_data = {
        "fiscal_year": target_year,
        "textual_inertia": None,
        "textual_inertia_reason": "No data available."
    }
    
    if db is not None:
        existing = db["textual_inertia_snapshots"].find_one({"ticker": t_symbol, "fiscal_year": target_year})
        if existing and existing.get("textual_inertia") is not None:
            res_data["textual_inertia"] = existing.get("textual_inertia")
            res_data["textual_inertia_reason"] = existing.get("textual_inertia_reason", "")
            print(f"[*] Found existing Textual Inertia snapshot for {t_symbol} {target_year}. Skipping LLM.")
            return res_data
    
    try:
        current_sec = get_sec_10k_section(t_symbol, target_year, "1A")
        prev_sec = get_sec_10k_section(t_symbol, prev_year, "1A")
        
        if current_sec and prev_sec and not current_sec.startswith("Risk Factors") and len(current_sec) > 500:
            clean_current = sanitize_for_prompt(current_sec, max_chars=SEC_TEXT_MAX_CHARS)
            clean_prev = sanitize_for_prompt(prev_sec, max_chars=SEC_TEXT_MAX_CHARS)
            
            message = (
                f"Please analyze the Risk Factors (Item 1A) text deviations for ticker: {t_symbol}\n\n"
                f"--- CURRENT YEAR {target_year} RISK FACTORS ---\n"
                f"{clean_current}\n\n"
                f"--- PREVIOUS YEAR {prev_year} RISK FACTORS ---\n"
                f"{clean_prev}\n\n"
            )
            
            res_inertia = None
            for attempt in range(6):
                try:
                    response = textual_inertia_agent.invoke({"input": message})
                    res_inertia = response.content
                    break
                except Exception as invoke_err:
                    err_str = str(invoke_err).lower()
                    if ("429" in err_str or "rate limit" in err_str or "too many requests" in err_str or "401" in err_str) and attempt < 5:
                        wait_sec = (2 ** attempt) * 4  # 4s, 8s, 16s, 32s, 64s
                        alt_key = os.getenv("NVIDIA_API_KEY_ALT", "").strip('"\' ')
                        if alt_key and os.getenv("NVIDIA_API_KEY") != alt_key:
                            print(f"[!] Rate limit hit for {t_symbol} {target_year} (Textual Inertia). Switching to NVIDIA_API_KEY_ALT...")
                            os.environ["NVIDIA_API_KEY"] = alt_key
                            try:
                                from functions.agents import create_textual_inertia_agent
                                from functions.utils.news.ingest import setup_clients_and_embeddings
                                _, _, _, kimi_llm_config, _, _, _ = setup_clients_and_embeddings()
                                textual_inertia_agent = create_textual_inertia_agent("textual_inertia_prompt.txt", kimi_llm_config)
                            except Exception as re_err:
                                print(f"[!] Warning rebuilding agent with alt key: {re_err}")
                        else:
                            print(f"[!] Rate limit 429 hit for {t_symbol} {target_year} (Textual Inertia). Retrying in {wait_sec}s (attempt {attempt+1}/5)...")
                        time.sleep(wait_sec)
                    else:
                        raise invoke_err

            if res_inertia:
                if "```json" in res_inertia:
                    res_inertia = res_inertia.split("```json")[1].split("```")[0].strip()
                elif "```" in res_inertia:
                    res_inertia = res_inertia.split("```")[1].split("```")[0].strip()
                    
                start_idx = res_inertia.find('{')
                end_idx = res_inertia.rfind('}')
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    res_inertia = res_inertia[start_idx:end_idx+1].strip()
                    
                parsed_inertia = json.loads(res_inertia)
                score_val = (
                    parsed_inertia.get("modification_score")
                    if parsed_inertia.get("modification_score") is not None
                    else (
                        parsed_inertia.get("textual_inertia")
                        if parsed_inertia.get("textual_inertia") is not None
                        else (
                            parsed_inertia.get("inertia_score")
                            if parsed_inertia.get("inertia_score") is not None
                            else parsed_inertia.get("score")
                        )
                    )
                )
                if score_val is not None:
                    res_data["textual_inertia"] = float(score_val)

                reason_val = (
                    parsed_inertia.get("reasoning_summary") or
                    parsed_inertia.get("reason") or
                    parsed_inertia.get("summary") or
                    parsed_inertia.get("explanation", "")
                )
                res_data["textual_inertia_reason"] = str(reason_val)
        else:
            res_data["textual_inertia_reason"] = f"Filing 10-K for year {target_year} or {prev_year} unavailable."
    except Exception as e:
        res_data["textual_inertia_reason"] = f"Extraction failed for year {target_year}: {e}"
        
    return res_data


def fetch_qa_tension_for_period(
    t_symbol: str,
    target_year: int,
    target_quarter: int,
    tension_extractor_agent,
    db = None
) -> dict:
    """Computes Q&A Tension for a specific fiscal year and quarter."""
    import time
    import os
    res_data = {
        "fiscal_year": target_year,
        "fiscal_quarter": target_quarter,
        "tension": None,
        "tension_reason": "No transcript available."
    }
    
    if db is not None:
        existing = db["qa_tension_snapshots"].find_one({"ticker": t_symbol, "fiscal_year": target_year, "fiscal_quarter": target_quarter})
        if existing and existing.get("qa_tension") is not None:
            res_data["tension"] = existing.get("qa_tension")
            res_data["tension_reason"] = existing.get("qa_tension_reason", "")
            print(f"[*] Found existing QA Tension snapshot for {t_symbol} {target_year}Q{target_quarter}. Skipping LLM.")
            return res_data
    
    try:
        transcript_data = fetch_and_split_transcript(t_symbol, year=target_year, quarter=target_quarter)
        qa_block = transcript_data.get("qa", "") if isinstance(transcript_data, dict) else ""
        
        if qa_block and len(qa_block) > 500:
            clean_qa = sanitize_for_prompt(qa_block, max_chars=SEC_TEXT_MAX_CHARS)
            
            message = (
                f"Please analyze corporate call Q&A tension for ticker: {t_symbol}\n\n"
                f"--- ANALYST Q&A BLOCK ({target_year} Q{target_quarter}) ---\n"
                f"{clean_qa}\n\n"
            )
            
            res_tension = None
            for attempt in range(6):
                try:
                    response = tension_extractor_agent.invoke({"input": message})
                    res_tension = response.content
                    break
                except Exception as invoke_err:
                    err_str = str(invoke_err).lower()
                    if ("429" in err_str or "rate limit" in err_str or "too many requests" in err_str or "401" in err_str) and attempt < 5:
                        wait_sec = (2 ** attempt) * 4  # 4s, 8s, 16s, 32s, 64s
                        alt_key = os.getenv("NVIDIA_API_KEY_ALT", "").strip('"\' ')
                        if alt_key and os.getenv("NVIDIA_API_KEY") != alt_key:
                            print(f"[!] Rate limit hit for {t_symbol} {target_year}Q{target_quarter} (QA Tension). Switching to NVIDIA_API_KEY_ALT...")
                            os.environ["NVIDIA_API_KEY"] = alt_key
                            try:
                                from functions.agents import create_tension_extractor_agent
                                from functions.utils.news.ingest import setup_clients_and_embeddings
                                _, _, _, kimi_llm_config, _, _, _ = setup_clients_and_embeddings()
                                tension_extractor_agent = create_tension_extractor_agent("tension_extractor_prompt.txt", kimi_llm_config)
                            except Exception as re_err:
                                print(f"[!] Warning rebuilding agent with alt key: {re_err}")
                        else:
                            print(f"[!] Rate limit 429 hit for {t_symbol} {target_year}Q{target_quarter} (QA Tension). Retrying in {wait_sec}s (attempt {attempt+1}/5)...")
                        time.sleep(wait_sec)
                    else:
                        raise invoke_err

            if res_tension:
                if "```json" in res_tension:
                    res_tension = res_tension.split("```json")[1].split("```")[0].strip()
                elif "```" in res_tension:
                    res_tension = res_tension.split("```")[1].split("```")[0].strip()
                    
                start_idx = res_tension.find('{')
                end_idx = res_tension.rfind('}')
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    res_tension = res_tension[start_idx:end_idx+1].strip()
                    
                parsed_tension = json.loads(res_tension)
                tension_val = (
                    parsed_tension.get("tension_score")
                    if parsed_tension.get("tension_score") is not None
                    else (
                        parsed_tension.get("tension")
                        if parsed_tension.get("tension") is not None
                        else (
                            parsed_tension.get("qa_tension")
                            if parsed_tension.get("qa_tension") is not None
                            else parsed_tension.get("score")
                        )
                    )
                )
                if tension_val is not None:
                    res_data["tension"] = float(tension_val)

                reason_val = (
                    parsed_tension.get("reasoning_summary") or
                    parsed_tension.get("reason") or
                    parsed_tension.get("summary") or
                    parsed_tension.get("explanation", "")
                )
                res_data["tension_reason"] = str(reason_val)
        else:
            res_data["tension_reason"] = f"Transcript for {target_year} Q{target_quarter} unavailable."
    except Exception as e:
        res_data["tension_reason"] = f"Extraction failed for {target_year} Q{target_quarter}: {e}"
        
    return res_data
