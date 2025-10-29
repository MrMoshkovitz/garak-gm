"""OpenAI Generator with Reactive Rate Limit Handling

This module provides a wrapper around the standard OpenAI generator that
automatically pauses execution when approaching rate limits (at 95% usage).
It uses response headers from the OpenAI API to reactively handle rate limiting.

Usage:
    Replace 'openai' with 'openai_rated' in your generator configuration:

    garak -m openai_rated.OpenAIRatedGenerator --target_name gpt-3.5-turbo

    Or in a probe config:
    generator: openai_rated

The wrapper is completely non-invasive and requires zero modifications to
existing garak code or configurations beyond the generator name change.
"""

import inspect
import json
import logging
import re
import time
from typing import List, Union

import openai
import backoff

from garak import _config
from garak.attempt import Message, Conversation
import garak.exception
from garak.generators.openai import OpenAIGenerator


class OpenAIRatedGenerator(OpenAIGenerator):
    """OpenAI generator wrapper with reactive rate limit handling and parallel attempts support.

    This generator monitors rate limit headers from OpenAI API responses and
    automatically pauses when usage reaches 99% of limits. It handles both
    request-based (RPM) and token-based (TPM) rate limits.

    Rate limit detection uses these OpenAI response headers:
    - x-ratelimit-remaining-requests / x-ratelimit-limit-requests
    - x-ratelimit-remaining-tokens / x-ratelimit-limit-tokens
    - x-ratelimit-reset-requests / x-ratelimit-reset-tokens

    The wrapper pauses execution and waits for the appropriate reset time when
    either rate limit threshold (99%) is exceeded.

    Parallel Attempts Support:
    When --parallel_attempts is used, each worker independently monitors rate limits
    from response headers. The 99% threshold provides sufficient buffer to prevent
    429 errors even without cross-process coordination.
    """

    generator_family_name = "OpenAI (Rate Limited)"
    parallel_capable = True  # Enable --parallel_attempts for faster API-based scanning

    def __init__(self, name="", config_root=_config):
        """Initialize OpenAI rated generator with parallel attempts support.

        Note: When using --parallel_attempts, each worker independently monitors
        rate limits from response headers. The 99% threshold provides sufficient
        buffer to prevent 429 errors even without cross-process state sharing.
        """
        super().__init__(name, config_root=config_root)

    @backoff.on_exception(
        backoff.fibo,
        (
            openai.RateLimitError,
            openai.InternalServerError,
            openai.APITimeoutError,
            openai.APIConnectionError,
            garak.exception.GarakBackoffTrigger,
        ),
        max_value=70,
    )
    def _call_model(
        self, prompt: Union[Conversation, List[dict]], generations_this_call: int = 1
    ) -> List[Union[Message, None]]:
        """Call the OpenAI model with reactive rate limit handling.

        This method wraps the parent class's model calling logic to intercept
        response headers and implement rate limiting. It maintains full
        compatibility with the parent class's return type and error handling.

        Args:
            prompt: The conversation or message list to send to the model
            generations_this_call: Number of generations to request (default: 1)

        Returns:
            List of Message objects or None values, identical to parent class

        Raises:
            RuntimeError: If response headers are missing or malformed
            Various OpenAI exceptions: Passed through from parent class
        """
        if self.client is None:
            self._load_client()

        # Build the same create_args as parent class
        create_args = {}
        if "n" not in self.suppressed_params:
            create_args["n"] = generations_this_call
        for arg in inspect.signature(self.generator.create).parameters:
            if arg == "model":
                create_args[arg] = self.name
                continue
            if arg == "extra_params":
                continue
            if hasattr(self, arg) and arg not in self.suppressed_params:
                if getattr(self, arg) is not None:
                    create_args[arg] = getattr(self, arg)

        if hasattr(self, "extra_params"):
            for k, v in self.extra_params.items():
                create_args[k] = v

        if self.generator == self.client.completions:
            if not isinstance(prompt, Conversation) or len(prompt.turns) > 1:
                msg = (
                    f"Expected a Conversation with one Turn for {self.generator_family_name} completions model {self.name}, but got {type(prompt)}. "
                    f"Returning nothing!"
                )
                logging.error(msg)
                return list()

            create_args["prompt"] = prompt.last_message().text

        elif self.generator == self.client.chat.completions:
            if isinstance(prompt, Conversation):
                messages = self._conversation_to_list(prompt)
            elif isinstance(prompt, list):
                messages = prompt
            else:
                msg = (
                    f"Expected a Conversation or list of dicts for {self.generator_family_name} Chat model {self.name}, but got {type(prompt)} instead. "
                    f"Returning nothing!"
                )
                logging.error(msg)
                return list()

            create_args["messages"] = messages

        # KEY MODIFICATION: Use with_raw_response to access headers
        # Each worker independently monitors rate limits from response headers
        # The 99% threshold provides sufficient buffer even in parallel mode
        try:
            # Make API call with header access
            raw_response = self.generator.with_raw_response.create(**create_args)

            # Check rate limits from response headers and pause if needed
            self._check_and_handle_rate_limits(raw_response.headers)

        except openai.RateLimitError as e:
            # Even on rate limit errors, try to extract headers if available
            if hasattr(e, 'response') and hasattr(e.response, 'headers'):
                logging.info(f"Rate limit error (429) - Headers: {dict(e.response.headers)}")
            # Re-raise to let backoff handle it
            raise
        except openai.BadRequestError as e:
            msg = "Bad request: " + str(repr(prompt))
            logging.exception(e)
            logging.error(msg)
            return [None]
        except json.decoder.JSONDecodeError as e:
            logging.exception(e)
            if self.retry_json:
                raise garak.exception.GarakBackoffTrigger from e
            else:
                raise e

        # Parse the actual response object (outside lock for performance)
        response = raw_response.parse()

        # Continue with original response handling
        if not hasattr(response, "choices"):
            logging.debug(
                "Did not get a well-formed response, retrying. Expected object with .choices member, got: '%s'"
                % repr(response)
            )
            msg = "no .choices member in generator response"
            if self.retry_json:
                raise garak.exception.GarakBackoffTrigger(msg)
            else:
                return [None]

        if self.generator == self.client.completions:
            return [Message(c.text) for c in response.choices]
        elif self.generator == self.client.chat.completions:
            return [Message(c.message.content) for c in response.choices]

    def _check_and_handle_rate_limits(self, headers):
        """Check rate limit headers and pause if threshold exceeded.

        Each worker independently monitors rate limits from response headers.
        In parallel mode, the 99% threshold provides sufficient buffer to prevent
        429 errors even without cross-process coordination.

        Monitors OpenAI rate limit headers from API responses:
        - TPM (Tokens per minute) - x-ratelimit-{limit|remaining|reset}-tokens
        - RPM (Requests per minute) - x-ratelimit-{limit|remaining|reset}-requests
        - TPD (Tokens per day) - if OpenAI sends daily headers
        - RPD (Requests per day) - if OpenAI sends daily headers

        Pauses execution when ANY limit reaches 95% usage to prevent 429 errors.

        Args:
            headers: HTTP response headers from OpenAI API
        """
        # Case-insensitive header lookup
        headers_lower = {k.lower(): v for k, v in headers.items()}

        # Extract all x-ratelimit headers dynamically
        ratelimit_headers = {k: v for k, v in headers_lower.items() if k.startswith('x-ratelimit-')}

        if not ratelimit_headers:
            logging.warning("No x-ratelimit-* headers found in response")
            return

        # Discover all limit types dynamically by parsing header patterns
        # Expected pattern: x-ratelimit-{remaining|limit|reset}-{type}
        # Examples: x-ratelimit-remaining-tokens, x-ratelimit-limit-requests, x-ratelimit-remaining-images
        all_limits = self._discover_all_limits(headers_lower)

        if not all_limits:
            logging.debug(f"Could not parse rate limits. Available headers: {list(ratelimit_headers.keys())}")
            return

        # Log all discovered rate limits
        log_parts = []
        for limit_name, limit_data in sorted(all_limits.items()):
            usage_pct = ((limit_data['limit'] - limit_data['remaining']) / limit_data['limit'] * 100) if limit_data['limit'] > 0 else 0

            # Create friendly label (e.g., "tokens" -> "TPM", "tokens-day" -> "TPD")
            label = self._get_limit_label(limit_name)

            log_parts.append(
                f"{label}: {limit_data['remaining']}/{limit_data['limit']} "
                f"({usage_pct:.1f}% used, resets in {limit_data['reset']})"
            )

        if log_parts:
            logging.info(f"Rate limits - {' | '.join(log_parts)}")

        # Check EVERY limit and pause if ANY hits 99% threshold
        # This ensures we never hit a 429, regardless of which limit triggers first
        for limit_name, limit_data in all_limits.items():
            limit = limit_data['limit']
            remaining = limit_data['remaining']
            reset = limit_data['reset']

            if limit > 0 and remaining <= (limit * 0.01):
                wait_time = self._parse_reset_time(reset)
                label = self._get_limit_label(limit_name)

                logging.warning(
                    f"⏸️  {label} at 95% usage ({remaining}/{limit} remaining)"
                )
                logging.warning(f"⏳ Pausing for {wait_time}s until reset")
                time.sleep(wait_time)
                logging.info(f"✅ Resuming after {label} reset")

    def _discover_all_limits(self, headers_lower):
        """Dynamically discover all rate limit types from OpenAI response headers.

        Parses x-ratelimit-* headers to find all limit types (tokens, requests)
        and their time periods (minute, day).

        Primary expected headers (per OpenAI docs):
        - x-ratelimit-{limit|remaining|reset}-tokens (TPM)
        - x-ratelimit-{limit|remaining|reset}-requests (RPM)

        Also checks for daily variants if OpenAI sends them.

        Args:
            headers_lower: Lowercase header dict

        Returns:
            Dict mapping limit_name -> {limit, remaining, reset}
            Example: {'tokens': {...}, 'requests': {...}, 'tokens-day': {...}}
        """
        all_limits = {}

        # Find all "remaining" headers to identify limit types
        remaining_headers = [k for k in headers_lower.keys() if k.startswith('x-ratelimit-remaining-')]

        for remaining_key in remaining_headers:
            # Extract the type name (e.g., "tokens", "requests", "images", "tokens-day")
            # Pattern: x-ratelimit-remaining-{type}
            type_name = remaining_key.replace('x-ratelimit-remaining-', '')

            # Build corresponding header keys
            limit_key = f'x-ratelimit-limit-{type_name}'
            reset_key = f'x-ratelimit-reset-{type_name}'

            # Check if we have all three required headers
            if limit_key in headers_lower and reset_key in headers_lower:
                try:
                    all_limits[type_name] = {
                        'limit': int(headers_lower[limit_key]),
                        'remaining': int(headers_lower[remaining_key]),
                        'reset': headers_lower[reset_key]
                    }
                except (ValueError, KeyError) as e:
                    logging.debug(f"Failed to parse limit for '{type_name}': {e}")

        return all_limits

    def _get_limit_label(self, limit_name):
        """Convert internal limit name to friendly label.

        Args:
            limit_name: Internal name like 'tokens', 'requests', 'tokens-day'

        Returns:
            Friendly label like 'TPM', 'RPM', 'TPD', 'RPD'
        """
        # Map documented OpenAI rate limit types
        label_map = {
            'tokens': 'TPM',           # Tokens per minute (documented)
            'requests': 'RPM',         # Requests per minute (documented)
            'tokens-day': 'TPD',       # Tokens per day (if sent)
            'requests-day': 'RPD',     # Requests per day (if sent)
        }

        # Return mapped label or create generic one for unexpected types
        if limit_name in label_map:
            return label_map[limit_name]

        # Generic fallback for any unexpected header patterns
        return limit_name.replace('-', '/').title()

    def _parse_reset_time(self, reset_str):
        """Convert OpenAI reset time format to seconds.

        OpenAI returns reset times in formats like:
        - "6m0s" -> 360 seconds
        - "1s" -> 1 second
        - "2m30s" -> 150 seconds

        Args:
            reset_str: Time string from x-ratelimit-reset-* header

        Returns:
            Integer number of seconds to wait

        Raises:
            ValueError: If reset_str format is not recognized
        """
        # Handle formats like "6m0s", "1s", "2m30s", "1h0m0s"
        pattern = r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?'
        match = re.match(pattern, reset_str)

        if not match:
            raise ValueError(f"Cannot parse reset time format: {reset_str}")

        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = float(match.group(3) or 0)

        total_seconds = (hours * 3600) + (minutes * 60) + seconds

        if total_seconds == 0:
            raise ValueError(f"Parsed reset time is zero: {reset_str}")

        return int(total_seconds) + 1  # Add 1 second buffer


DEFAULT_CLASS = "OpenAIRatedGenerator"
