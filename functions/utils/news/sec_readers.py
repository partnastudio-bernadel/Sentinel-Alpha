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
    print("\n[+] Step 2: Running Unstructured Reading Workers Layer...")
    indicators_report_data = {}
    
    for t_symbol in tickers_to_query:
        print(f"[*] Analyzing qualitative indicators for asset: {t_symbol}...")
        indicators_report_data[t_symbol] = {
            "textual_inertia": None,
            "textual_inertia_reason": "No data available.",
            "tension": None,
            "tension_reason": "No data available."
        }
        
        # A. Item 1A (Risk Factors) Textual Inertia (Lazy Prices)
        try:
            current_year = 2024
            prev_year = 2023
            current_sec = get_sec_10k_section(t_symbol, current_year, "1A")
            prev_sec = get_sec_10k_section(t_symbol, prev_year, "1A")
            
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
                
                response = textual_inertia_agent.invoke({"input": message})
                res_inertia = response.content
                
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
                indicators_report_data[t_symbol]["textual_inertia"] = float(parsed_inertia.get("modification_score", 0.0))
                indicators_report_data[t_symbol]["textual_inertia_reason"] = parsed_inertia.get("reasoning_summary", "")
            else:
                indicators_report_data[t_symbol]["textual_inertia_reason"] = "Risk factors filings unavailable."
                print(f"[!] Warning: Risk factors filings unavailable for {t_symbol}. Textual inertia will be set to None. Formulas will lack this data.")
        except Exception as e:
            print(f"[!] Warning: failed to compute Textual Inertia for {t_symbol}: {e}. Formulas will lack this data.")
            indicators_report_data[t_symbol]["textual_inertia_reason"] = f"Extraction failed: {e}"

        # B. Analyst Q&A Tension Extractor
        try:
            transcript_data = fetch_and_split_transcript(t_symbol)
            qa_block = transcript_data.get("qa", "")
            
            if qa_block and len(qa_block) > 500:
                print(f"[*] Running Q&A Tension Extractor Agent on earnings call for {t_symbol}...")
                
                # Sanitize inputs to prevent prompt injection
                clean_qa = sanitize_for_prompt(qa_block, max_chars=SEC_TEXT_MAX_CHARS)
                
                message = (
                    f"Please analyze corporate call Q&A tension for ticker: {t_symbol}\n\n"
                    f"--- ANALYST Q&A BLOCK ---\n"
                    f"{clean_qa}\n\n"
                )
                
                response = tension_extractor_agent.invoke({"input": message})
                res_tension = response.content
                
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
                indicators_report_data[t_symbol]["tension"] = float(parsed_tension.get("tension_score", 0.0))
                indicators_report_data[t_symbol]["tension_reason"] = parsed_tension.get("reasoning_summary", "")
            else:
                indicators_report_data[t_symbol]["tension_reason"] = "Earnings call Q&A transcript unavailable."
                print(f"[!] Warning: Earnings call Q&A transcript unavailable for {t_symbol}. Tension will be set to None. Formulas will lack this data.")
        except Exception as e:
            print(f"[!] Warning: failed to extract Analyst Q&A tension for {t_symbol}: {e}. Formulas will lack this data.")
            indicators_report_data[t_symbol]["tension_reason"] = f"Extraction failed: {e}"

    return indicators_report_data
