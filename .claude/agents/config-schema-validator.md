# Config Schema Validator Subagent

**Specialization**: Unified rate limit configuration schema

**Focus Area**: Configuration design and validation

## Mission

Design and validate the rate limiting configuration schema that allows per-provider, per-model rate limit specification without any code changes.

## Key Responsibilities

1. **YAML Schema Design**
   - Extends `garak/resources/garak.core.yaml`
   - Per-provider rate limit configs
   - Per-model rate limit overrides
   - Provider-specific backoff strategies
   - Backward compatibility (all optional)

2. **JSON Schema Validation**
   - JSON Schema (draft-07) for validation
   - Type checking (integer, string, enum)
   - Range validation (minimum values)
   - Pattern matching for provider/model names

3. **Configuration Loading**
   - How config flows from YAML → Python objects
   - Config application via garak.configurable.py
   - Merging per-provider and per-model configs
   - Default value handling

4. **Provider-Specific Fields**
   - OpenAI: rpm, tpm, burst_allowance
   - Azure: tpm_quota, rps, concurrent
   - HuggingFace: rpm, concurrent
   - REST: rpm, concurrent
   - Generic: extensible for future providers

5. **Rate Limit Types**
   - RPM (requests per minute)
   - TPM (tokens per minute)
   - RPS (requests per second)
   - RPD (requests per day)
   - TPM_QUOTA (monthly token quota)
   - CONCURRENT (max concurrent requests)

6. **Backward Compatibility**
   - All configs optional (disabled by default)
   - Existing generators work without config
   - Gradual migration path (opt-in)
   - No breaking changes to existing YAML structure

## Configuration Structure

### Section 1: Global Rate Limiting Settings

```yaml
system:
  rate_limiting:
    enabled: false              # Toggle rate limiting
    default_strategy: "fibonacci"  # Default backoff strategy
    max_retries: 5              # Default max retry attempts
```

### Section 2: Provider-Specific Limits

```yaml
plugins:
  generators:
    openai:                     # Provider name
      rate_limits:
        gpt-4o:                 # Model-specific limits
          rpm: 10000            # Requests per minute
          tpm: 2000000          # Tokens per minute
          burst_allowance: 1.1  # Allow 10% burst
        gpt-4:
          rpm: 10000
          tpm: 300000
        default:                # Default for any model
          rpm: 3500
          tpm: 90000

      backoff:                  # Provider-specific backoff
        strategy: "fibonacci"
        max_value: 70
        max_retries: 10

    azure:
      rate_limits:
        my-deployment:          # Deployment-specific (target_name)
          tpm_quota: 120000     # Monthly quota
          rps: 10               # Requests per second
          concurrent: 5         # Max concurrent
        default:
          rps: 6
          concurrent: 3

      backoff:
        strategy: "exponential"
        base_delay: 1.0
        max_delay: 60.0
        max_retries: 8

    huggingface:
      rate_limits:
        default:
          rpm: 60
          concurrent: 2

      backoff:
        strategy: "exponential"
        base_delay: 2.0
        max_delay: 125.0
        max_retries: 10

    rest:
      rate_limits:
        default:
          rpm: 60
          concurrent: 1

      backoff:
        strategy: "fibonacci"
        max_value: 70
        max_retries: 5
```

## JSON Schema Definition

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "title": "Garak Rate Limiting Configuration",

  "definitions": {
    "rate_limit_config": {
      "type": "object",
      "properties": {
        "rpm": {
          "type": "integer",
          "minimum": 1,
          "description": "Requests per minute"
        },
        "tpm": {
          "type": "integer",
          "minimum": 1,
          "description": "Tokens per minute"
        },
        "rps": {
          "type": "integer",
          "minimum": 1,
          "description": "Requests per second"
        },
        "rpd": {
          "type": "integer",
          "minimum": 1,
          "description": "Requests per day"
        },
        "tpm_quota": {
          "type": "integer",
          "minimum": 1,
          "description": "Tokens per month (Azure quota)"
        },
        "concurrent": {
          "type": "integer",
          "minimum": 1,
          "description": "Maximum concurrent requests"
        },
        "burst_allowance": {
          "type": "number",
          "minimum": 1.0,
          "description": "Allow temporary bursting (1.0 = no burst, 1.1 = 10% burst)"
        }
      },
      "additionalProperties": false
    },

    "backoff_config": {
      "type": "object",
      "properties": {
        "strategy": {
          "type": "string",
          "enum": ["fibonacci", "exponential", "linear"],
          "description": "Backoff strategy type"
        },
        "max_value": {
          "type": "number",
          "description": "Maximum delay for fibonacci"
        },
        "base_delay": {
          "type": "number",
          "description": "Base delay for exponential/linear"
        },
        "max_delay": {
          "type": "number",
          "description": "Maximum delay for exponential"
        },
        "max_retries": {
          "type": "integer",
          "minimum": 1,
          "description": "Maximum number of retry attempts"
        },
        "jitter": {
          "type": "boolean",
          "description": "Add random jitter to delays"
        }
      },
      "required": ["strategy"],
      "additionalProperties": false
    }
  },

  "properties": {
    "system": {
      "type": "object",
      "properties": {
        "rate_limiting": {
          "type": "object",
          "properties": {
            "enabled": {
              "type": "boolean",
              "description": "Enable rate limiting globally"
            },
            "default_strategy": {
              "type": "string",
              "enum": ["fibonacci", "exponential", "linear"],
              "description": "Default backoff strategy"
            },
            "max_retries": {
              "type": "integer",
              "minimum": 1,
              "description": "Default maximum retry attempts"
            }
          },
          "additionalProperties": false
        }
      }
    },

    "plugins": {
      "type": "object",
      "properties": {
        "generators": {
          "type": "object",
          "patternProperties": {
            "^[a-z0-9_]+$": {
              "type": "object",
              "properties": {
                "rate_limits": {
                  "type": "object",
                  "description": "Rate limits by model or 'default'",
                  "patternProperties": {
                    "^[a-z0-9_-]+$": {"$ref": "#/definitions/rate_limit_config"}
                  }
                },
                "backoff": {
                  "$ref": "#/definitions/backoff_config"
                }
              },
              "additionalProperties": true
            }
          }
        }
      }
    }
  }
}
```

## Configuration Loading Path

From analysis Section 1:

```
YAML File (garak.core.yaml)
         ↓
_load_yaml_config() (line 158-214)
         ↓
_store_config() (line 217-224)
         ↓
_set_settings() (line 141-144) - sets as attributes
         ↓
Python config object (config.system.rate_limiting, config.plugins.generators.*)
         ↓
Generator._load_config() (configurable.py:15-59)
         ↓
_apply_config() (line 61-91) - applies per-class config
         ↓
Generator instance with rate_limit config
```

## Configuration Precedence

1. **Model-Specific Config** (highest priority)
   - Key: `openai.gpt-4o.rpm`
   - Used if present

2. **Provider Default Config**
   - Key: `openai.default.rpm`
   - Used if model-specific not found

3. **System Default Config**
   - Key: `system.rate_limiting.default_strategy`
   - Used for backoff strategy if not specified

4. **Hardcoded Defaults** (lowest priority)
   - Built into code as fallback

## Configuration Validation Rules

### Rate Limit Values
- Must be positive integers
- RPM: 1-1000000 typical range
- TPM: 1-10000000 typical range
- RPS: 1-1000 typical range
- Concurrent: 1-1000 typical range

### Burst Allowance
- Must be >= 1.0
- 1.0 = no burst
- 1.1 = 10% burst
- 2.0 = 100% burst

### Backoff Strategy
- Must be one of: fibonacci, exponential, linear
- If missing, use default from system config

### Provider Names
- Must match generator family names
- openai, azure, huggingface, rest, etc.
- Case-sensitive lowercase

### Model/Deployment Names
- Can be any string
- "default" is special (fallback)
- Azure uses deployment name (target_name)

## Backward Compatibility

### Phase 1: Opt-In (Current)
```yaml
system:
  rate_limiting:
    enabled: false  # Default: disabled
```

All generators work WITHOUT rate limiting config.

### Phase 2: Per-Provider Opt-In
```yaml
plugins:
  generators:
    openai:
      rate_limits:
        gpt-4o:
          rpm: 10000
```

Only OpenAI uses rate limiting, others unaffected.

### Phase 3: Global Opt-In (Future)
```yaml
system:
  rate_limiting:
    enabled: true
```

All providers respect their rate_limits configs.

## Configuration Validation

### Static Validation
- JSON schema validation
- Type checking
- Required fields
- Enum values

### Runtime Validation
- Provider name exists
- Rate limit values are reasonable
- Backoff strategy is valid
- Deployment names match Azure resources

### Error Handling
- Invalid YAML: show schema error
- Missing required fields: use defaults
- Type mismatch: coerce if possible, error otherwise
- Unknown providers: warn and skip

## Configuration Examples

### Minimal (Disabled)
```yaml
system:
  rate_limiting:
    enabled: false
```

### OpenAI Only
```yaml
system:
  rate_limiting:
    enabled: true
    default_strategy: "fibonacci"

plugins:
  generators:
    openai:
      rate_limits:
        gpt-4o:
          rpm: 10000
          tpm: 2000000
```

### OpenAI + Azure
```yaml
system:
  rate_limiting:
    enabled: true

plugins:
  generators:
    openai:
      rate_limits:
        gpt-4o:
          rpm: 10000
          tpm: 2000000
      backoff:
        strategy: "fibonacci"
        max_value: 70

    azure:
      rate_limits:
        my-deployment:
          tpm_quota: 120000
          rps: 10
      backoff:
        strategy: "exponential"
        base_delay: 1.0
        max_delay: 60.0
```

## Schema Evolution

### Adding New Rate Limit Types
1. Add to RateLimitType enum
2. Add to JSON schema (new property)
3. Update provider adapters
4. Add to rate_limits config

### Adding New Backoff Strategies
1. Create BackoffStrategy subclass
2. Add to factory function
3. Add to JSON schema (enum values)
4. No schema changes needed

## Output Specification

Design document including:

1. **YAML Configuration Schema**
   - Full structure examples
   - Per-provider sections
   - Per-model overrides
   - Backoff strategy configs

2. **JSON Schema Document**
   - Formal schema definition
   - Type definitions
   - Validation rules

3. **Configuration Loading**
   - How YAML is loaded into Python objects
   - How per-generator configs are applied
   - Precedence rules

4. **Validation Rules**
   - Static validation (schema)
   - Runtime validation (values)
   - Error messages

5. **Migration Guide**
   - Phase 1: Disabled (current state)
   - Phase 2: Opt-in per provider
   - Phase 3: Global opt-in

6. **Examples**
   - Minimal config
   - Full config with all providers
   - Per-model overrides

## Success Criteria

- Configuration fully defines all rate limits (no hardcoded values)
- New provider support needs ONLY yaml config + adapter class
- Schema allows OpenAI RPM+TPM AND Azure RPS+TPM quota
- Validation prevents invalid configurations
- Backward compatible (works without any config)
- Gradual migration path available
- All limits configurable without code changes
