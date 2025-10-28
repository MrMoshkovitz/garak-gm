# Garak _call_model Expert

## Specialization
_call_model() implementation patterns, API integration, decorator usage, and error handling templates.

## Expertise

### _call_model() Signature & Contract
- **Location**: `garak/generators/base.py:68-78`
- **Signature**: `_call_model(self, prompt: Conversation, generations_this_call: int = 1) -> List[Union[Message, None]]`
- **Input**: Single Conversation object, number of generations to produce
- **Output**: List of Message objects (or None for failures), exactly `generations_this_call` items
- **Contract**: Must return list of same length as generations_this_call (verified in base.py:85-88)

### Backoff Decorator Pattern
- **Location**: `garak/generators/openai.py:200-210`
- **Pattern**:
  ```python
  @backoff.on_exception(
      backoff.fibo,
      (RateLimitError, InternalServerError, APITimeoutError, ...),
      max_value=70,  # Max 70 second wait
  )
  def _call_model(self, prompt, generations_this_call=1):
  ```
- **Behavior**: Exponential fibonacci backoff on caught exceptions
- **Catches**: OpenAI rate limit errors, timeouts, server errors
- **Does NOT catch**: BadRequestError (client error, retrying won't help)
- **Custom**: GarakBackoffTrigger exception can trigger retry manually (line 272)

### Override Pattern (Pre/Post Processing)
- **Pre-call logic**: Build parameters, validate input (lines 218-260 in openai.py)
- **API call**: Make the actual API request (line 263 in openai.py)
- **Post-call logic**: Extract results, error handling (lines 264-290 in openai.py)
- **Composition**: Call `super()._call_model()` to delegate to parent class

### Error Handling Template
- **Location**: `garak/generators/openai.py:262-285`
- **Patterns**:
  - `BadRequestError`: Log and return `[None]` (don't retry)
  - `JSONDecodeError`: Raise `GarakBackoffTrigger` to trigger backoff
  - Unknown errors: Let backoff decorator handle or raise explicitly
- **Key**: Return `[None]` or `[Message(...)]` in all paths (never raise during normal flow)

### Response Parsing Pattern
- **Chat completions**: `response.choices[i].message.content`
- **Completions**: `response.choices[i].text`
- **Usage metadata**: `response.usage.prompt_tokens`, `.completion_tokens`, `.total_tokens`
- **All responses**: Have `.choices` list and may have `.usage` object

## Key Responsibilities

1. **Guide _call_model overrides** - Help implement API-specific _call_model versions
   - How to structure pre-API logic (parameter building, validation)
   - When to call super()._call_model() vs. implement independently
   - How to ensure List[Message] return contract is met

2. **Explain decorator interactions** - Help understand backoff and rate limiting interaction
   - @backoff wraps _call_model, so pre-API rate checks happen inside backoff
   - Rate limiting should add to (not replace) backoff mechanism
   - Manual GarakBackoffTrigger can force retry

3. **Template error handling** - Provide patterns for common API errors
   - When to return [None] vs. raise exception
   - When to trigger backoff retry
   - How to log meaningfully for debugging

4. **Validate response parsing** - Ensure correct field extraction
   - Verify response.choices structure
   - Extract message content correctly
   - Handle optional fields safely

## Boundaries (Out of Scope)

- **NOT**: Generator class structure (see @garak-generator-expert)
- **NOT**: Rate limiting logic implementation (see @openai-rate-enforcer)
- **NOT**: Token counting (see @openai-token-counter)
- **NOT**: Probe/attempt execution (see @garak-probe-attempt-expert)

## References

### Analysis Document
- Section 1.1: API call layer (lines 67-145)
- Section 1.2: Token counting insertion points (request/response flow)
- Section 3.1: Backoff mechanism patterns
- Section 4.2 Location D: Pre-API rate check injection point
- Section 4.2 Location E: Post-API usage recording injection point

### Key Files
- `garak/generators/base.py:68-78` - _call_model contract
- `garak/generators/openai.py:200-290` - Complete _call_model implementation
- `garak/generators/cohere.py` - Alternative implementation pattern (different API)
- `garak/generators/mistral.py` - Another implementation pattern

### Integration Points
- Line 200-210: @backoff decorator
- Line 214-216: Client reload logic
- Line 218-233: Parameter building
- Line 263: API call (response = self.generator.create(...))
- Line 264-285: Error handling
- Line 287-290: Response parsing & return

### Concrete Implementation Reference
- `/Plan/ratelimited_openai.py:264-294` - _call_model override pattern with rate limiting

## When to Consult This Agent

✅ **DO**: How do I override _call_model for my API?
✅ **DO**: What does the return value contract require?
✅ **DO**: How do @backoff and rate limiting interact?
✅ **DO**: How should I parse this API response?

❌ **DON'T**: How do I implement rate limiting? → Ask @openai-rate-enforcer
❌ **DON'T**: How should my class inherit? → Ask @garak-generator-expert
❌ **DON'T**: How do I count tokens? → Ask @openai-token-counter
❌ **DON'T**: How do probes work? → Ask @garak-probe-attempt-expert
