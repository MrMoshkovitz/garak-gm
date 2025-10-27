"""OpenAI Rate-Limited Generator

A reactive rate limiter that wraps OpenAI generator to respect API rate limits.
Reads response headers (x-ratelimit-* fields) and pauses when approaching limits.

Features:
- No modifications to core garak code
- Monitors RPM (requests per minute) and TPM (tokens per minute)
- Pauses at 95% usage threshold
- Auto-resumes when limits reset
- Graceful fallback when headers are missing
"""

import logging
import re
import time
from typing import List, Union

import openai
import backoff

from garak.attempt import Message, Conversation
import garak.exception
from garak.generators.openai import OpenAIGenerator


def parse_reset_time(reset_string: str) -> float:
    """Parse OpenAI rate limit reset time string to seconds.

    Args:
        reset_string: Time string in format like "1s", "6m0s", "1h30m45s"

    Returns:
        Number of seconds until reset

    Examples:
        >>> parse_reset_time("1s")
        1.0
        >>> parse_reset_time("6m0s")
        360.0
        >>> parse_reset_time("1h30m45s")
        5445.0
    """
    if not reset_string:
        return 0.0

    total_seconds = 0.0

    # Extract hours
    hours_match = re.search(r'(\d+)h', reset_string)
    if hours_match:
        total_seconds += int(hours_match.group(1)) * 3600

    # Extract minutes
    minutes_match = re.search(r'(\d+)m', reset_string)
    if minutes_match:
        total_seconds += int(minutes_match.group(1)) * 60

    # Extract seconds
    seconds_match = re.search(r'(\d+)s', reset_string)
    if seconds_match:
        total_seconds += int(seconds_match.group(1))

    return total_seconds


class OpenAIRatedGenerator(OpenAIGenerator):
    """Rate-limited wrapper for OpenAI generator.

    Monitors rate limit headers from OpenAI API responses and pauses when
    approaching limits (95% threshold). Automatically resumes after rate
    limits reset.

    Usage:
        garak --model_type openai_rated --model_name gpt-4o-mini --probes test.Blank
    """

    generator_family_name = "OpenAI (Rate Limited)"

    # Rate limiting configuration
    PAUSE_THRESHOLD = 0.05  # Pause when remaining drops below 5% (95% usage)

    def __init__(self, name="", config_root=None):
        """Initialize the rate-limited generator."""
        super().__init__(name, config_root)
        self.rate_limit_pause_count = 0
        logging.info(
            f"Initialized {self.generator_family_name} with rate limiting "
            f"(pause threshold: {(1-self.PAUSE_THRESHOLD)*100}% usage)"
        )

    def _extract_rate_limit_headers(self, headers: dict) -> dict:
        """Extract rate limit information from response headers.

        Args:
            headers: HTTP response headers from OpenAI API

        Returns:
            Dictionary with rate limit information:
            {
                'limit_requests': int,
                'limit_tokens': int,
                'remaining_requests': int,
                'remaining_tokens': int,
                'reset_requests': str,
                'reset_tokens': str
            }
        """
        rate_info = {}

        # Header mapping (case-insensitive lookup)
        header_map = {
            'x-ratelimit-limit-requests': 'limit_requests',
            'x-ratelimit-limit-tokens': 'limit_tokens',
            'x-ratelimit-remaining-requests': 'remaining_requests',
            'x-ratelimit-remaining-tokens': 'remaining_tokens',
            'x-ratelimit-reset-requests': 'reset_requests',
            'x-ratelimit-reset-tokens': 'reset_tokens',
        }

        # Convert headers to lowercase dict for case-insensitive lookup
        headers_lower = {k.lower(): v for k, v in headers.items()}

        for header_name, key in header_map.items():
            if header_name in headers_lower:
                value = headers_lower[header_name]
                # Convert to int for numeric values, keep string for reset times
                if 'reset' in key:
                    rate_info[key] = value
                else:
                    try:
                        rate_info[key] = int(value)
                    except (ValueError, TypeError):
                        logging.debug(f"Could not parse {header_name}: {value}")

        return rate_info

    def _should_pause(self, rate_info: dict) -> tuple[bool, float]:
        """Determine if we should pause based on rate limit usage.

        Args:
            rate_info: Rate limit information from headers

        Returns:
            Tuple of (should_pause: bool, sleep_duration: float)
        """
        if not rate_info:
            return False, 0.0

        # Check if we have the required fields
        required_fields = [
            'limit_requests', 'remaining_requests',
            'limit_tokens', 'remaining_tokens'
        ]

        if not all(field in rate_info for field in required_fields):
            return False, 0.0

        # Calculate usage percentages
        request_remaining_pct = (
            rate_info['remaining_requests'] / rate_info['limit_requests']
            if rate_info['limit_requests'] > 0 else 1.0
        )

        token_remaining_pct = (
            rate_info['remaining_tokens'] / rate_info['limit_tokens']
            if rate_info['limit_tokens'] > 0 else 1.0
        )

        # Pause if either metric drops below threshold
        should_pause = (
            request_remaining_pct < self.PAUSE_THRESHOLD or
            token_remaining_pct < self.PAUSE_THRESHOLD
        )

        if should_pause:
            # Calculate sleep duration (max of both reset times)
            reset_requests_sec = parse_reset_time(
                rate_info.get('reset_requests', '')
            )
            reset_tokens_sec = parse_reset_time(
                rate_info.get('reset_tokens', '')
            )
            sleep_duration = max(reset_requests_sec, reset_tokens_sec)

            logging.info(
                f"Rate limit approaching: "
                f"Requests={rate_info['remaining_requests']}/{rate_info['limit_requests']} "
                f"({request_remaining_pct*100:.1f}%), "
                f"Tokens={rate_info['remaining_tokens']}/{rate_info['limit_tokens']} "
                f"({token_remaining_pct*100:.1f}%)"
            )

            return True, sleep_duration

        return False, 0.0

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
        """Call the OpenAI model with rate limit monitoring.

        This method wraps the parent class's API call to monitor rate limit
        headers and pause when approaching limits.

        Args:
            prompt: Input conversation or message list
            generations_this_call: Number of generations to request

        Returns:
            List of generated messages
        """
        if self.client is None:
            self._load_client()

        # Build the API call parameters (same as parent class)
        import inspect

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

        # Prepare prompt based on model type
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

        # Make the API call with raw response to access headers
        try:
            # Use with_raw_response to get access to HTTP headers
            raw_response = self.generator.with_raw_response.create(**create_args)

            # Extract rate limit headers
            headers = dict(raw_response.headers)
            rate_info = self._extract_rate_limit_headers(headers)

            # Parse the actual response
            response = raw_response.parse()

            # Check if we should pause based on rate limits
            should_pause, sleep_duration = self._should_pause(rate_info)

            if should_pause and sleep_duration > 0:
                self.rate_limit_pause_count += 1
                logging.warning(
                    f"Rate limit threshold reached (pause #{self.rate_limit_pause_count}). "
                    f"Sleeping for {sleep_duration:.1f} seconds until reset..."
                )
                time.sleep(sleep_duration)
                logging.info("Rate limit reset complete. Resuming operations.")

        except openai.BadRequestError as e:
            msg = "Bad request: " + str(repr(prompt))
            logging.exception(e)
            logging.error(msg)
            return [None]
        except Exception as e:
            # If we can't access headers or something goes wrong,
            # fall back to normal behavior
            logging.debug(f"Could not access rate limit headers: {e}")
            # Re-raise specific exceptions for backoff handling
            if isinstance(e, (
                openai.RateLimitError,
                openai.InternalServerError,
                openai.APITimeoutError,
                openai.APIConnectionError,
                garak.exception.GarakBackoffTrigger,
            )):
                raise
            # For other exceptions, try normal call
            return super()._call_model(prompt, generations_this_call)

        # Process and return results
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


DEFAULT_CLASS = "OpenAIRatedGenerator"
