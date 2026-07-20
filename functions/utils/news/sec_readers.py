import json
from functions.tools.edgar_tools import get_sec_10k_section
from functions.tools.transcript_tools import fetch_and_split_transcript
from functions.utils.common.sanitize import sanitize_for_prompt
from functions.constants import SEC_TEXT_MAX_CHARS

def execute_reading_workers(
    tickers_to_query: list,
    textual_inertia_agent,
    tension_extractor_agent
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
        try:
            current_year = 2024
            prev_year = 2023
            current_sec = get_sec_10k_section(t_symbol, current_year, "1A")
            prev_sec = get_sec_10k_section(t_symbol, prev_year, "1A")
            
            ticker_data["fiscal_year"] = current_year
            
            if current_sec and prev_sec and not current_sec.startswith("Risk Factors") and len(current_sec) > 500:
                print(f"[*] Running Textual Inertia Agent on consecutive filings for {t_symbol}...")
                
                # Sanitize inputs to prevent prompt injection
                clean_current = sanitize_for_prompt(current_sec, max_chars=SEC_TEXT_MAX_CHARS)
                clean_prev = sanitize_for_prompt(prev_sec, max_chars=SEC_TEXT_MAX_CHARS)
                
                message = (
                    f"Please analyze the Risk Factors (Item 1A) text deviations for ticker: {t_symbol}\n\n"
                    f"--- CURRENT YEAR {current_year} RISK FACTORS ---\n"
                    f"{clean_current}\n\n"
                    f"--- PREVIOUS YEAR {prev_year} RISK FACTORS ---\n"
                    f"{clean_prev}\n\n"
                )
                
                # Retry loop for 429 rate limits
                import time
                res_inertia = None
                for attempt in range(4):
                    try:
                        response = textual_inertia_agent.invoke({"input": message})
                        res_inertia = response.content
                        break
                    except Exception as invoke_err:
                        err_str = str(invoke_err).lower()
                        if ("429" in err_str or "rate limit" in err_str or "too many requests" in err_str) and attempt < 3:
                            wait_sec = (2 ** attempt) * 3
                            print(f"[!] Rate limit 429 hit for {t_symbol} (Textual Inertia). Retrying in {wait_sec}s (attempt {attempt+1}/3)...")
                            time.sleep(wait_sec)
                        else:
                            raise invoke_err

                if res_inertia:
                    # Strip markdown JSON blocks if present
                    if "```json" in res_inertia:
                        res_inertia = res_inertia.split("```json")[1].split("```")[0].strip()
                    elif "```" in res_inertia:
                        res_inertia = res_inertia.split("```")[1].split("```")[0].strip()
                        
                    start_idx = res_inertia.find('{')
                    end_idx = res_inertia.rfind('}')
                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        res_inertia = res_inertia[start_idx:end_idx+1].strip()
                        
                    parsed_inertia = json.loads(res_inertia)
                    ticker_data["textual_inertia"] = float(parsed_inertia.get("modification_score", 0.0))
                    ticker_data["textual_inertia_reason"] = parsed_inertia.get("reasoning_summary", "")
            else:
                ticker_data["textual_inertia_reason"] = "Risk factors filings unavailable."
                print(f"[!] Warning: Risk factors filings unavailable for {t_symbol}. Textual inertia will be set to None. Formulas will lack this data.")
        except Exception as e:
            print(f"[!] Warning: failed to compute Textual Inertia for {t_symbol}: {e}. Formulas will lack this data.")
            ticker_data["textual_inertia_reason"] = f"Extraction failed: {e}"

        # B. Analyst Q&A Tension Extractor
        try:
            transcript_data = fetch_and_split_transcript(t_symbol)
            qa_block = transcript_data.get("qa", "")
            
            ticker_data["fiscal_quarter"] = 1  # Default / recent quarter
            
            if qa_block and len(qa_block) > 500:
                print(f"[*] Running Q&A Tension Extractor Agent on earnings call for {t_symbol}...")
                
                # Sanitize inputs to prevent prompt injection
                clean_qa = sanitize_for_prompt(qa_block, max_chars=SEC_TEXT_MAX_CHARS)
                
                message = (
                    f"Please analyze corporate call Q&A tension for ticker: {t_symbol}\n\n"
                    f"--- ANALYST Q&A BLOCK ---\n"
                    f"{clean_qa}\n\n"
                )
                
                # Retry loop for 429 rate limits
                import time
                res_tension = None
                for attempt in range(4):
                    try:
                        response = tension_extractor_agent.invoke({"input": message})
                        res_tension = response.content
                        break
                    except Exception as invoke_err:
                        err_str = str(invoke_err).lower()
                        if ("429" in err_str or "rate limit" in err_str or "too many requests" in err_str) and attempt < 3:
                            wait_sec = (2 ** attempt) * 3
                            print(f"[!] Rate limit 429 hit for {t_symbol} (QA Tension). Retrying in {wait_sec}s (attempt {attempt+1}/3)...")
                            time.sleep(wait_sec)
                        else:
                            raise invoke_err

                if res_tension:
                    # Strip markdown JSON blocks if present
                    if "```json" in res_tension:
                        res_tension = res_tension.split("```json")[1].split("```")[0].strip()
                    elif "```" in res_tension:
                        res_tension = res_tension.split("```")[1].split("```")[0].strip()
                        
                    start_idx = res_tension.find('{')
                    end_idx = res_tension.rfind('}')
                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        res_tension = res_tension[start_idx:end_idx+1].strip()
                        
                    parsed_tension = json.loads(res_tension)
                    ticker_data["tension"] = float(parsed_tension.get("tension_score", 0.0))
                    ticker_data["tension_reason"] = parsed_tension.get("reasoning_summary", "")
            else:
                ticker_data["tension_reason"] = "Earnings call Q&A transcript unavailable."
                print(f"[!] Warning: Earnings call Q&A transcript unavailable for {t_symbol}. Tension will be set to None. Formulas will lack this data.")
        except Exception as e:
            print(f"[!] Warning: failed to extract Analyst Q&A tension for {t_symbol}: {e}. Formulas will lack this data.")
            ticker_data["tension_reason"] = f"Extraction failed: {e}"
            
        return t_symbol, ticker_data

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tickers_to_query)) as executor:
        results = executor.map(process_ticker, tickers_to_query)
        for t_symbol, ticker_data in results:
            indicators_report_data[t_symbol] = ticker_data

    return indicators_report_data


def fetch_textual_inertia_for_year(
    t_symbol: str,
    target_year: int,
    textual_inertia_agent
) -> dict:
    """Computes Textual Inertia for a specific fiscal year (comparing target_year vs target_year - 1)."""
    import time
    prev_year = target_year - 1
    res_data = {
        "fiscal_year": target_year,
        "textual_inertia": None,
        "textual_inertia_reason": "No data available."
    }
    
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
                res_data["textual_inertia"] = float(parsed_inertia.get("modification_score", 0.0))
                res_data["textual_inertia_reason"] = parsed_inertia.get("reasoning_summary", "")
        else:
            res_data["textual_inertia_reason"] = f"Filing 10-K for year {target_year} or {prev_year} unavailable."
    except Exception as e:
        res_data["textual_inertia_reason"] = f"Extraction failed for year {target_year}: {e}"
        
    return res_data


def fetch_qa_tension_for_period(
    t_symbol: str,
    target_year: int,
    target_quarter: int,
    tension_extractor_agent
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
                res_data["tension"] = float(parsed_tension.get("tension_score", 0.0))
                res_data["tension_reason"] = parsed_tension.get("reasoning_summary", "")
        else:
            res_data["tension_reason"] = f"Transcript for {target_year} Q{target_quarter} unavailable."
    except Exception as e:
        res_data["tension_reason"] = f"Extraction failed for {target_year} Q{target_quarter}: {e}"
        
    return res_data
