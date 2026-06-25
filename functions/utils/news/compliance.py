import json
from functions.utils.math.formulas import normalize_weights, calculate_raw_sentiment
from functions.utils.logging.compliance_logger import log_compliance_event
from functions.constants import SENTIMENT_ALPHA, ALLOCATION_DRIFT_LIMIT

def validate_compliance_limits(
    ticker: str,
    is_etf: bool,
    constituents: list,
    final_report: dict,
    merged_result,
    indicators_report_data: dict,
    scribe_agent
) -> dict:
    """Simulates compliance limit validation (L1 drift check) and triggers Thesis-CoT Scribe override justification if drift > 15%."""
    print("\n[+] Step 3: Running compliance allocation gateway checks...")
    
    aggregate_score = final_report.get("aggregate_score", 0.0)
    
    if is_etf and constituents:
        base_weights = {c["ticker"]: float(c["weight"]) for c in constituents}
        normalized_base = normalize_weights(base_weights)
        
        # Calculate drift per asset
        violations = []
        for t_symbol, w_base in normalized_base.items():
            t_news_sentiment = 0.0
            # Retrieve specific constituent score if present in merged scored results
            if isinstance(merged_result, list):
                for r in merged_result:
                    if r.get("ticker") == t_symbol:
                        t_news_sentiment = float(calculate_raw_sentiment(r))
                        break
            elif isinstance(merged_result, dict) and merged_result.get("ticker") == t_symbol:
                t_news_sentiment = float(calculate_raw_sentiment(merged_result))
                
            w_proposed = w_base * (1.0 + SENTIMENT_ALPHA * t_news_sentiment)
            drift = abs(w_proposed - w_base)
            if drift > ALLOCATION_DRIFT_LIMIT:
                violations.append({
                    "ticker": t_symbol,
                    "base": w_base,
                    "proposed": w_proposed,
                    "drift": drift
                })
    else:
        w_base = 1.0
        w_proposed = w_base * (1.0 + SENTIMENT_ALPHA * aggregate_score)
        drift = abs(w_proposed - w_base)
        violations = []
        if drift > ALLOCATION_DRIFT_LIMIT:
            violations.append({
                "ticker": ticker,
                "base": w_base,
                "proposed": w_proposed,
                "drift": drift
            })

    if violations:
        print(f"[Compliance] {int(ALLOCATION_DRIFT_LIMIT * 100)}% Allocation Drift Limit Violated! Active violations count: {len(violations)}")
        for v in violations:
            print(f"  - Asset {v['ticker']}: Proposed Weight {v['proposed']:.4f} (Base: {v['base']:.4f}, Drift: {v['drift']*100:.2f}%)")
            
        print("[Compliance] Spawning Thesis-CoT Scribe Agent to generate justification narrative...")
        
        # Trigger Thesis-CoT Scribe Agent to write legal overrides justification
        message = (
            f"Compliance warning triggered. Please write an override justification for the following drift:\n"
            f"Violations details: {json.dumps(violations, indent=2)}\n"
            f"Qualitative Indicators: {json.dumps(indicators_report_data, indent=2)}\n"
            f"Pipeline Consolidated Report: {json.dumps(final_report, indent=2)}\n"
            f"Investor override requested reason: Institutional portfolio reallocation based on alpha indicators."
        )
        
        response = scribe_agent.invoke({"input": message})
        res_scribe = response.content
        
        # Strip markdown JSON blocks if present
        if "```json" in res_scribe:
            res_scribe = res_scribe.split("```json")[1].split("```")[0].strip()
        elif "```" in res_scribe:
            res_scribe = res_scribe.split("```")[1].split("```")[0].strip()
            
        start_idx = res_scribe.find('{')
        end_idx = res_scribe.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            res_scribe = res_scribe[start_idx:end_idx+1].strip()
        try:
            parsed_scribe = json.loads(res_scribe)
            compliance_thesis = parsed_scribe.get("compliance_thesis", "Override approved based on qualitative indicator drift.")
            
            # Log the override event to local file logs
            log_compliance_event(
                event_type="OVERRIDE",
                metadata={
                    "ticker": ticker,
                    "violations": violations,
                    "indicators": indicators_report_data,
                    "compliance_thesis": compliance_thesis,
                    "status": "APPROVED"
                }
            )
            
            # Enrich final report payload with compliance thesis narrative
            final_report["compliance_override"] = {
                "limit_violated": f"{int(ALLOCATION_DRIFT_LIMIT * 100)}% allocation drift limit exceeded",
                "justification": compliance_thesis,
                "status": "APPROVED_AND_LOGGED"
            }
        except Exception as ex:
            print(f"[!] Warning: failed to parse Scribe justification JSON: {ex}. Logging raw string.")
            log_compliance_event(
                event_type="OVERRIDE_PARSE_FAILURE",
                metadata={
                    "ticker": ticker,
                    "raw_scribe_output": res_scribe,
                    "violations": violations,
                    "status": "APPROVED_WITH_WARNING"
                }
            )
            final_report["compliance_override"] = {
                "limit_violated": f"{int(ALLOCATION_DRIFT_LIMIT * 100)}% allocation drift limit exceeded",
                "justification": "Manual compliance override approved.",
                "status": "APPROVED_WITH_WARNING"
            }
    else:
        print(f"[Compliance] Allocation drift gateway validation passed successfully (drift <= {int(ALLOCATION_DRIFT_LIMIT * 100)}%).")

    return final_report
