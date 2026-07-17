import os
import sys
import pandas as pd
from dotenv import load_dotenv
from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings
from functions.tools.openbb import fetch_etf_holdings_from_openbb
from functions.aggregator.aggregator import fetch_aggregate_all_news
from functions.tools.prepare_articles import prepare_articles

# Resolve paths
current_file_dir = os.path.dirname(os.path.abspath(__file__))
news_dir = current_file_dir
utils_dir = os.path.dirname(news_dir)
functions_dir = os.path.dirname(utils_dir)
sentiment_dir = os.path.dirname(functions_dir)

def setup_clients_and_embeddings(env_path: str = None, csv_path: str = None) -> tuple:
    """Resolves configuration paths, loads environment variables, and builds calibration database."""
    if env_path is None:
        env_path = os.path.join(sentiment_dir, ".env.local")
        if not os.path.exists(env_path):
            env_path = os.path.join(sentiment_dir, ".env")
            
    if csv_path is None:
        csv_path = os.path.join(sentiment_dir, "data", "financial_sentiment.csv")
        
    prompt_dir = os.path.join(sentiment_dir, "prompts")
    schema_dir = os.path.join(sentiment_dir, "schema_json")

    # Verify that essential paths exist before proceeding
    if not os.path.exists(env_path):
        raise FileNotFoundError(f"Configuration file not found at: {env_path}")

    # Load environment variables
    load_dotenv(env_path, override=True)
    
    nvidia_embedding_model = os.getenv("NVIDIA_EMBEDDING_MODEL", "nvidia/nv-embed-v1").strip('"\' ')
    nvidia_api_key = os.getenv("NVIDIA_API_KEY", "").strip('"\' ')
    nvidia_api_endpoint = os.getenv("NVIDIA_API_ENDPOINT", "https://integrate.api.nvidia.com/v1").strip('"\' ')
    
    if not nvidia_api_key:
        raise ValueError("NVIDIA_API_KEY is not set in the environment configuration.")

    # Setup embeddings & LLM configurations
    embeddings = NVIDIAEmbeddings(
        model=nvidia_embedding_model,
        api_key=nvidia_api_key,
        base_url=nvidia_api_endpoint
    )
    
    # Setup configs: LLM config for Scorer and base config for CIO
    nvidia_base_model = os.getenv("NVIDIA_TOOLING_MODEL", "").strip('"\' ')
    hf_api_key = os.getenv("HUGGINGFACE_API_KEY", "").strip('"\' ')
    hf_model_name = os.getenv("HUGGINGFACE_MODEL_NAME_FEATHERLESS", "curiousily/Llama-3-8B-Instruct-Finance-RAG").strip('"\' ')
    hf_base_url = os.getenv("HUGGINGFACE_BASE_URL", "https://router.huggingface.co/v1").strip('"\' ')
    
    llm_config = {
        "model": hf_model_name,
        "base_url": hf_base_url,
        "api_key": hf_api_key
    }
    base_llm_config = {
        "model": nvidia_base_model,
        "base_url": nvidia_api_endpoint,
        "api_key": nvidia_api_key
    }

    # Intercept and override deprecated Hugging Face model in-memory (comply with "No edits to env files" rule)
    def override_deprecated_model(config):
        if not config:
            return config
        config = config.copy()
        model_name = config.get("model", "")
        if "curiousily/Llama-3-8B-Instruct-Finance-RAG" in model_name:
            config["model"] = "meta-llama/Meta-Llama-3.1-8B-Instruct"
        return config

    llm_config = override_deprecated_model(llm_config)

    # Setup Kimi configuration for the reading and compliance workers
    nvidia_base_model_alt = os.getenv("NVIDIA_BASE_MODEL_ALT", "moonshotai/kimi-k2.6").strip('"\' ')
    kimi_llm_config = {
        "model": nvidia_base_model_alt,
        "base_url": nvidia_api_endpoint,
        "api_key": nvidia_api_key
    }

    # Use MongoDB vector store for calibration examples
    from langchain_mongodb import MongoDBAtlasVectorSearch
    from functions.utils.db.connect import get_vector_collection
    
    collection = get_vector_collection()
    db = MongoDBAtlasVectorSearch(
        collection=collection,
        embedding=embeddings,
        index_name="vector_index",
        text_key="sentence",
        embedding_key="embedding"
    )

    return db, llm_config, base_llm_config, kimi_llm_config, prompt_dir, schema_dir, embeddings

def fetch_and_decompose_holdings(ticker: str, holdings: int, limit: int, db) -> tuple:
    """Checks ETF decomposition and fetches news articles for the target ticker or its constituents."""
    print("\n[+] Step 1: Running ETF Decomposition check...")
    df_holdings = fetch_etf_holdings_from_openbb(ticker)
    
    is_etf = False
    constituents = []
    decomp_data = {}
    
    if not df_holdings.empty:
        df_holdings = df_holdings.sort_values(by="fund_weight", ascending=False)
        candidate_constituents = df_holdings.to_dict(orient="records")
        candidate_constituents = [
            c for c in candidate_constituents
            if c.get("ticker") and str(c.get("ticker")).strip().upper() != ticker.upper()
        ]
        
        if len(candidate_constituents) > 0:
            constituents = candidate_constituents[:holdings]
            is_etf = True
            decomp_data = {
                "ticker": ticker,
                "is_etf": True,
                "error_flag": False,
                "constituents": [
                    {"ticker": c["ticker"], "weight": float(c["fund_weight"])}
                    for c in constituents
                ]
            }

    if not is_etf:
        decomp_data = {
            "ticker": ticker,
            "is_etf": False,
            "error_flag": False,
            "constituents": []
        }

    all_articles = []
    if is_etf and constituents:
        import concurrent.futures
        print(f"[+] Decomposed ETF. Top {len(constituents)} constituents to analyze: {[c['ticker'] for c in constituents]}")
        
        def process_constituent(const):
            c_ticker = const["ticker"]
            print(f"[*] Fetching news for constituent: {c_ticker}...")
            try:
                df_c_news = fetch_aggregate_all_news(symbol=c_ticker, limit=100)
                if df_c_news.empty:
                    print(f"[-] No articles found for constituent {c_ticker}. Skipping.")
                    return []
                prepared = prepare_articles(df_c_news, db, limit=limit)
                for art in prepared:
                    art["ticker"] = c_ticker
                return prepared
            except Exception as ex:
                print(f"[-] Error processing constituent {c_ticker}: {ex}. Skipping.")
                return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(constituents)) as executor:
            results = executor.map(process_constituent, constituents)
            for res in results:
                all_articles.extend(res)
    else:
        print(f"[*] Ticker {ticker} is a single stock or failed decomposition. Processing fallback...")
        try:
            df_news = fetch_aggregate_all_news(symbol=ticker, limit=100)
            if not df_news.empty:
                prepared = prepare_articles(df_news, db, limit=limit)
                for art in prepared:
                    art["ticker"] = ticker
                all_articles.extend(prepared)
        except Exception as ex:
            print(f"[-] Error processing ticker {ticker}: {ex}.")

    return is_etf, constituents, decomp_data, all_articles
