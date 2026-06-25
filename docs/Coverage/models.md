# Macro Ingestion - Model Testing Results

This document tracks the testing results and capabilities of various LLM models when running the Macro Ingestion and Economic Surprise calculation workflow under the new **ReAct (Reason + Action)** orchestration framework.

## Model Capability & Testing Matrix

| Model Identifier | Model Class | ReAct Trace Quality | Tool Calling Reliability | Vulnerability to Prompt Example Mimicry | Key Observations & Testing Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`minimaxai/minimax-m3`** | Small / Lightweight | Poor | Low (Bypassed tool calls) | High (Directly repeated example JSON) | Fails to trigger `get_alpha_vantage_historical_std`. Tends to copy the few-shot template placeholders. Not recommended for sub-agent tooling roles. |
| **`meta/llama-3.1-8b-instruct`** | Medium | Good | Medium (Fails on parallel tool calls) | High | Successfully generates reasoning traces, but requires explicit type constraints. On NVIDIA NIM, it fails with a 500 error if it attempts parallel tool calling, requiring `parallel_tool_calls=False` in `llm_config`. Vulnerable to constituent fabrication/hallucination when tools return empty results. |
| **`mistralai/mistral-nemotron`** | Medium-Large | Excellent | High | Low | Excellent instruction following. Generates clear thoughts and matches tool signatures accurately. Good candidate for scrapers and baseline calculators. |
| **`qwen/qwen3-next-80b-a3b-instruct`** | Large | Excellent | High | Low | High reasoning capacity. Autonomous tool execution is very stable. Excels at returning raw JSON blocks without surrounding markdown prose. |
| **`meta/llama-3.1-70b-instruct`** | Large | Excellent | Very High | Low | Standard production model. Robustly handles multi-agent orchestration, complex tool inputs, and nested chat control logic. Can initially pass string representation of floats resulting in `Error: '<=' not supported between instances of 'str' and 'float'`, but successfully self-corrects when strict python typing is enforced. |
| **`moonshotai/kimi-k2.6`** | Large | Good | High | Low | Base model candidate. Successfully retrieves calendar data and standard deviation, though it can occasionally write out tool suggestion structures in its final answer text block rather than executing purely via native tools, requiring robust parser cleanup. |
| **`deepseek-ai/deepseek-v4-flash`** | Medium-Large | Excellent | High (Sequential execution) | Low | Tooling model candidate. Demonstrates high structural compliance and executes sequential tools cleanly. However, it can place `TERMINATE` or trailing text inside unclosed code blocks, requiring strict `{` to `}` boundary extraction. |

---

## Key Optimization Takeaways

1. **Tool Definition Quality:** 
   Larger models (`llama-3.1-70b`, `qwen3-next`) read docstrings and argument types precisely. Smaller models require simplified, primitive types and fewer complex parameter options.
   
2. **Double Braces in String Templates:** 
   When designing prompts in Python frameworks (like AutoGen) where prompts are processed by `.format()`, all literal JSON blocks in example traces must double their braces (`{{` and `}}`) to avoid template parsing `KeyError` exceptions.

3. **Orchestration Turn Limits:** 
   Constraining nested chat limits to `max_turns: 2` ensures the sub-agents return their results in one direct interaction loop. This prevents the orchestrator's thoughts from leaking back to sub-agents and being overwritten by the summary method.

4. **Context Payload Truncation on Small Models:**
   Passing large raw payloads (e.g. 401 events, ~80 KB JSON) to smaller models (`minimax-m3`, `llama-3.1-8b`) causes silent truncation or attention loss. The agent will act as if only the first event in the list (e.g., German Retail Sales) exists. Tool wrappers must filter data at the Python/code level (`event_filter` and `currency_filter`) to return lightweight payloads (~12 events or fewer).

5. **Literalness of 70B Models vs. 8B Models:**
   * **8B Model:** Less strict. It will parse and calculate values even if they are poorly formatted or ambiguously mapped in history.
   * **70B Model:** Extremely instruction-compliant and literal. If instructions command it to extract details from "sub-agent responses in the context," but the context is injected as a message it *sent* itself (due to incorrect `recipient.send` direction), it will refuse to calculate with it. It will instead explain the scenario hypothetically using dummy variables. Correcting the AutoGen message flow to `sender.send(..., recipient=recipient)` is required to make 70B process the data as incoming input.
   * **Currency Ambiguity:** In a list of global CPI releases (CHF, USD, EUR), 70B will not guess which release is matching a generic "CPI" indicator. Clarifying the target country/currency (e.g. `"USD"`) in prompts is mandatory for precise output.

6. **Constituent Fabrication & Hallucination in 8B Models**:
   When running helper tooling agents (like the `Decomposition_Worker`) on smaller models like `llama-3.1-8b-instruct`, the agent is prone to hallucinating placeholders. For example, if the OpenBB holdings tool returns an empty constituent list for a single-stock ticker (e.g., `MSFT`), the 8B model tends to fabricate a constituent structure (`"ticker": "MSFT", "weight": 1.0`) and set `"error_flag": false` instead of executing the failure path (`"error_flag\": true`). This triggers unexpected nested tool-calling loops (such as calling `calculate_portfolio_sentiment` on single stocks) in downstream agents. Downstream orchestration code must handle such fallbacks and enforce high auto-reply counts to prevent early thread termination during these unexpected loops. See the detailed [Hallucination & Limitation Profile: meta/llama-3.1-8b-instruct](#hallucination--limitation-profile-metallama-31-8b-instruct) below.

7. **ReAct vs. Native Tool Calling Conflict:**
   When a system prompt instructs the model to follow a text-based ReAct trace (`- **Thought:**`, `- **Action:**`) while AutoGen simultaneously registers native function calls, a structural conflict arises. The model may use placeholder values in its native tool call to fulfil the JSON schema quickly, intending to do its "real" reasoning in the text output. When the tool response returns an error, the model fails to associate the native tool error with its internal ReAct loop, causing it to repeat the same placeholder arguments in an infinite loop rather than self-correcting. **Resolution**: Remove ReAct text-format instructions from system prompts entirely when using AutoGen's native `register_function` tool calling.

8. **Sub-Agent Final Answer Leakage into Context Payload:**
   When Kimi-K2.6 and similar models produce a "Final Answer" block that contains a tool suggestion trace (e.g., `***** Suggested tool call ...`), the `clean_react_summary` parser strips it down to non-data tokens (e.g., `**`), effectively blanking the value being passed to the orchestrator. This caused the `deepseek-v4-flash` orchestrator to receive an empty standard deviation value. The correct mitigation is to parse the actual numeric return value from the tool response message in the chat history rather than parsing the model's free-text summary for the value.

9. **NVIDIA NIM Parallel Tool Calling Constraint**:
   Certain endpoints (such as NVIDIA NIM hosting `meta/llama-3.1-8b-instruct`) enforce a strict API schema restriction allowing only a single tool call per inference turn. When the agent attempts parallel tool calling (requesting multiple math operations in a single response), the endpoint rejects it with a 500 error (`This model only supports single tool-calls at once!`). Setting `"parallel_tool_calls": False` in `llm_config` is required to force sequential execution.

10. **Resilient JSON Extraction against Trailing Postambles (`TERMINATE`)**:
   Some models (such as `deepseek-v4-flash`) successfully write sequential tool calls and output a formatted JSON block but may append the `TERMINATE` instruction directly after the closing JSON brace (or leave code blocks unclosed). This triggers a JSON parse error due to trailing extra data. The parser must always run a `{` to `}` boundary extraction as the final pass when `is_json=True` to strip away any trailing text.

---

## Hallucination & Limitation Profile: meta/llama-3.1-8b-instruct

During execution of the nested news-delegation flow, several distinct hallucination modes were identified for `meta/llama-3.1-8b-instruct`. Below is a detailed breakdown of these behaviors and the mitigation strategies implemented in the orchestrator:

### 1. Constituent & Weight Fabrication (Decomposition Phase)
* **Observed Behavior:** When the `Decomposition_Worker` is queried with a single stock ticker (e.g., `MSFT`), calling the `fetch_etf_holdings_from_openbb` tool yields an empty holdings list. Instead of marking `"error_flag": true` and reporting that the ticker is not an ETF, the 8B model tends to fabricate a synthetic constituent profile, setting `"ticker": "MSFT"`, `"weight": 1.0` (or `100`), and setting `"error_flag": false`.
* **Implication:** The downstream orchestrator receives a false-positive indication that the ticker is an ETF, initiating unintended sub-agent loop runs and attempting to score `MSFT` as if it were a multi-holding portfolio.
* **Mitigation:** The system reply handler parses the JSON and performs a Python-level validation. If the output contains only the original ticker itself or the tool output returns empty, the handler automatically treats the asset as a single stock, bypassing the LLM's fabricated constituent structure.

### 2. Arithmetic & Aggregation Hallucinations (Math Calculations)
* **Observed Behavior:** When requested to calculate weighted averages or portfolio-weighted sentiment scores in natural language or simple code generation, the 8B model consistently hallucinates correct-looking but mathematically incorrect values (e.g., estimating `(0.32 * 0.38) + (0.88 * 0.33) + (0.18 * 0.30)` as `0.55` instead of `0.46`). It also struggles with multi-decimal precision or normalizing weights to sum to exactly `1.0`.
* **Implication:** Incorrect raw and portfolio sentiment values are recorded in the final output report, undermining statistical validity.
* **Mitigation:** Removed all mathematical calculation tasks from the LLM prompt. Registered explicit Python tools (`calculate_raw_sentiment`, `normalize_weights`, `calculate_portfolio_sentiment`) for the `cio_agent` to invoke. The model is strictly instructed to call these functions and inject the return values directly into its final output without manual recalculation.

### 3. Preamble & Formatting Leakage (JSON Strictness)
* **Observed Behavior:** Despite system prompt rules forbidding any text outside of the JSON payload, the 8B model frequently prefixes its output with pleasantries (e.g., *"Here is the requested analysis:"*) or wraps the output in markdown code blocks (` ```json ... ``` `).
* **Implication:** Standard JSON parsers (`json.loads`) crash when parsing the raw response text.
* **Mitigation:** Implemented a robust regex-based extraction utility ([extract_and_clean_response](file:///d:/PartnaStudio/sentinel/stack/FinRobot-IntentChain/sentiment/functions/utils/common/read_and_clean.py)) that strips preambles, postambles, and code block delimiters before attempting to deserialize the JSON.

### 4. Parameter and Signature Hallucinations (Tool Calling)
* **Observed Behavior:** If tool description docstrings are not extremely rigid, the 8B model will hallucinate non-existent arguments (e.g., passing `ticker="MSFT"` instead of `symbol="MSFT"` or generating additional fields not defined in the function signature).
* **Implication:** Python-level tool executions fail with type or argument errors, crashing the AutoGen agent loop.
* **Mitigation:** Standardized all tool docstrings, simplified signature arguments, and restricted parameters to primitive types (e.g., `str`, `int`, `float`, `dict`) as outlined in the Prompt and Docstring standards.

### 5. Loop Retention & Auto-Reply Termination
* **Observed Behavior:** Under complex orchestration flows (such as looping over multiple constituents to fetch and score news), the 8B model fails to recognize completion signals (like `TERMINATE`) and can get stuck in conversational loops, either repeating previous tool calls or explaining its previous output.
* **Implication:** The orchestrator either hits max-turn limits or terminates early with partial results.
* **Mitigation:** Increased `max_consecutive_auto_reply` to `15` to accommodate the multi-turn constituent batch loops, and adjusted `is_termination_msg` logic to gracefully handle `None` content outputs from tool call message structures.

---

## Hallucination & Limitation Profile: meta/llama-3.1-70b-instruct

### 1. Initial Type Mismatch in Tool Arguments
* **Observed Behavior:** On its first tool calling attempt, the 70B model may pass string representations (e.g., `"0"`, `"0.5"`, `"1.141"`) instead of floats to numeric parameters in calculation functions like `calculate_macro_surprise`. This causes Python to raise:
  ```
  Error: '<=' not supported between instances of 'str' and 'float'
  ```
* **Implication:** The first turn calculation fails, requiring an additional turn to resolve.
* **Mitigation/Self-Correction:** Enforce strict type checking at the Python function level instead of using permissive conversion/coercion (which can mask mistakes and cause calculation errors or loop issues). When the model receives the explicit python `TypeError` in its chat history, it successfully reads the error details and self-corrects in the subsequent turn, passing pure floats.

