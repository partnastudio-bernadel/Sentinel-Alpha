import json
from functions.tools.custom_reply import extract_json_array, merge_scored_results

def batch_score_articles(all_articles: list, scorer_agent) -> tuple:
    """Scores news articles in batches of 5 using the LangChain Scorer Agent."""
    batch_size = 5
    batch_results = []
    
    for i in range(0, len(all_articles), batch_size):
        batch = all_articles[i:i + batch_size]
        print(f"[*] Batching scoring pipeline: processing articles {i+1} to {min(i+batch_size, len(all_articles))} of {len(all_articles)}")
        
        message = (
            "Please score the following articles according to your instructions:\n\n"
            f"{json.dumps(batch, indent=2)}\n\n"
            "Respond with the list of scored articles."
        )
        
        # Invoke the LangGraph react agent
        response = scorer_agent.invoke({"messages": [("user", message)]})
        # The final answer is typically the last message content
        summary_content = response["messages"][-1].content
        
        scored_data = extract_json_array(summary_content)
        if scored_data is not None:
            batch_results.append(scored_data)
        else:
            try:
                clean_content = summary_content
                batch_results.append(json.loads(clean_content))
            except Exception as e:
                print(f"[!] Error parsing batch response: {e}. Raw content: {summary_content}")

    # Merge batch results
    merged_result = merge_scored_results(batch_results)
    scorer_summary = json.dumps(merged_result, indent=2)
    return merged_result, scorer_summary
