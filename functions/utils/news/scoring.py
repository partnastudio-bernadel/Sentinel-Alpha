import json
import asyncio
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
                if summary_content and summary_content.strip():
                    batch_results.append(json.loads(summary_content))
            except Exception as e:
                print(f"[!] Error parsing batch response: {e}. Raw content: {summary_content}")

    # Merge batch results
    merged_result = merge_scored_results(batch_results)
    scorer_summary = json.dumps(merged_result, indent=2)
    return merged_result, scorer_summary

async def async_score_batch_with_retry(batch, scorer_agent, max_retries=5):
    for attempt in range(max_retries):
        try:
            message = (
                "Please score the following articles according to your instructions:\n\n"
                f"{json.dumps(batch, indent=2)}\n\n"
                "Respond with the list of scored articles."
            )
            # Use ainvoke for async execution
            response = await scorer_agent.ainvoke({"messages": [("user", message)]})
            summary_content = response["messages"][-1].content
            
            scored_data = extract_json_array(summary_content)
            if scored_data is not None:
                return scored_data
            else:
                try:
                    if summary_content and summary_content.strip():
                        return json.loads(summary_content)
                except Exception as e:
                    print(f"[!] Error parsing async batch response: {e}. Raw content: {summary_content}")
                    return None
        except Exception as e:
            error_str = str(e).lower()
            if "503" in error_str or "429" in error_str or "exhausted" in error_str or "rate limit" in error_str:
                wait_time = 2 ** attempt
                print(f"[!] Rate limit hit (attempt {attempt+1}/{max_retries}). Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                raise e
    print("[!] Max retries exceeded for async batch.")
    return None

async def async_batch_score_articles_runner(all_articles: list, scorer_agent, max_concurrency: int = 5) -> tuple:
    batch_size = 5
    semaphore = asyncio.Semaphore(max_concurrency)
    
    async def bounded_score_batch(batch):
        async with semaphore:
            return await async_score_batch_with_retry(batch, scorer_agent)

    tasks = []
    
    for i in range(0, len(all_articles), batch_size):
        batch = all_articles[i:i + batch_size]
        print(f"[*] Async Batching scoring pipeline: scheduling articles {i+1} to {min(i+batch_size, len(all_articles))} of {len(all_articles)}")
        tasks.append(bounded_score_batch(batch))
        
    results = await asyncio.gather(*tasks)
    
    batch_results = [r for r in results if r is not None]
    merged_result = merge_scored_results(batch_results)
    scorer_summary = json.dumps(merged_result, indent=2)
    return merged_result, scorer_summary

def async_batch_score_articles(all_articles: list, scorer_agent) -> tuple:
    """Entry point to run the async scorer from a synchronous context."""
    return asyncio.run(async_batch_score_articles_runner(all_articles, scorer_agent))
