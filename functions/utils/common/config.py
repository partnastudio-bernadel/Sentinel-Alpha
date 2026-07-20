import os
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_openai import ChatOpenAI

def build_chat_model(model: str, base_url: str = None, api_key: str = None, temperature: float = None):
    """
    Unified model factory returning appropriate LangChain chat instances
    for NVIDIA NIM or HuggingFace (OpenAI-compatible router) endpoints.
    """
    if not api_key:
        if (base_url and "nvidia" in str(base_url).lower()) or (model and "nvidia" in model.lower()):
            api_key = os.getenv("NVIDIA_API_KEY", "").strip('"\' ')
        else:
            api_key = os.getenv("HUGGINGFACE_API_KEY", "").strip('"\' ')

    # Format base URL
    if base_url:
        base_url = base_url.strip('"\' ')

    if (base_url and "nvidia" in base_url.lower()) or (model and "nvidia" in model.lower()):
        llm = ChatNVIDIA(
            model=model,
            api_key=api_key,
            base_url=base_url or "https://integrate.api.nvidia.com/v1",
            temperature=temperature
        )
    else:
        # ChatOpenAI uses temperature=None by default, but it's safe to pass if provided
        kwargs = {
            "model": model,
            "openai_api_key": api_key,
            "openai_api_base": base_url or "https://router.huggingface.co/v1"
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
            
        llm = ChatOpenAI(**kwargs)

    # Force single tool-calling mode for NVIDIA NIM compatibility
    try:
        original_bind_tools = llm.bind_tools
        def patched_bind_tools(tools, **kwargs):
            kwargs["parallel_tool_calls"] = False
            return original_bind_tools(tools, **kwargs)
        object.__setattr__(llm, "bind_tools", patched_bind_tools)
    except AttributeError:
        pass

    return llm