"""OpenAI Generator with Reactive Rate Limit Handling

This generator extends OpenAIGenerator to add reactive rate limit management
by parsing response headers from the OpenAI API. It pauses execution when
approaching rate limits (95% threshold) to prevent 429 errors.

Usage:
    garak --model_type openai_rated --target_name gpt-3.5-turbo --probe <probe>

Philosophy: Minimal viable wrapper - surgical integration, zero garak core modifications
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


def _parse_time_string(time_str: str) -> float:
    """Parse OpenAI time format strings to seconds.

    Handles formats like:
    - "1s" -> 1.0
    - "6m0s" -> 360.0
    - "1h30m45s" -> 5445.0

    Args:
        time_str: Time string from rate limit reset headers

    Returns:
        Total seconds as float

    Raises:
        ValueError: If time string format is invalid
    """
    if not time_str or not isinstance(time_str, str):
        raise ValueError(f"Invalid time string: {time_str}")

    total_seconds = 0.0

    # Extract hours
    hours_match = re.search(r'(\d+)h', time_str)
    if hours_match:
        total_seconds += int(hours_match.group(1)) * 3600

    # Extract minutes
    minutes_match = re.search(r'(\d+)m', time_str)
    if minutes_match:
        total_seconds += int(minutes_match.group(1)) * 60

    # Extract seconds
    seconds_match = re.search(r'(\d+)s', time_str)
    if seconds_match:
        total_seconds += int(seconds_match.group(1))

    # If no matches found, it might be a plain number or invalid
    if total_seconds == 0.0 and not any([hours_match, minutes_match, seconds_match]):
        # Try parsing as plain number with optional 's' suffix
        clean_str = time_str.strip().rstrip('s')
        try:
            total_seconds = float(clean_str)
        except ValueError:
            raise ValueError(f"Could not parse time string: {time_str}")

    return total_seconds


class OpenAIRatedGenerator(OpenAIGenerator):
    """OpenAI Generator with reactive rate limit handling via response headers.

    This generator wraps OpenAIGenerator to add automatic rate limit management:
    - Parses rate limit headers from each OpenAI API response
    - Monitors both request and token limits
    - Pauses when within 5% of either limit (95% threshold = 5% safety margin)
    - Automatically resumes after rate limit reset period
    - Raises explicit errors if rate limit headers are missing

    Rate Limit Headers Monitored:
    - x-ratelimit-remaining-requests / x-ratelimit-limit-requests
    - x-ratelimit-remaining-tokens / x-ratelimit-limit-tokens
    - x-ratelimit-reset-requests (time until request limit resets)
    - x-ratelimit-reset-tokens (time until token limit resets)

    Safety Features:
    - 5% capacity margin (pauses at 95% utilization)
    - 2 second buffer on wait times (accounts for clock skew)
    - INFO level logging for visibility
    - No fallback behavior (fails explicitly if headers missing)

    Constraints:
    - Single-threaded only (parallel requests not supported)
    - Reactive approach (checks after each call, not proactive)
    - Does not handle Batch API queue limits

    Inherits all functionality from OpenAIGenerator including model support,
    configuration, and error handling.
    """

    # Safety margin: pause when remaining capacity drops below this threshold
    RATE_LIMIT_THRESHOLD = 0.05  # 5% remaining = 95% utilized

    # Buffer to add to reset wait times (accounts for clock skew)
    RESET_WAIT_BUFFER_SECONDS = 2

    generator_family_name = "OpenAI_Rated"

    def _parse_rate_limit_headers(self, headers) -> dict:
        """Extract and parse rate limit values from OpenAI response headers.

        Args:
            headers: HTTP response headers from OpenAI API

        Returns:
            Dictionary with parsed rate limit information:
            {
                'remaining_requests': int,
                'remaining_tokens': int,
                'reset_requests': float (seconds),
                'reset_tokens': float (seconds),
                'limit_requests': int,
                'limit_tokens': int
            }

        Raises:
            ValueError: If any required rate limit header is missing or malformed
        """
        required_headers = {
            'x-ratelimit-remaining-requests': 'remaining_requests',
            'x-ratelimit-remaining-tokens': 'remaining_tokens',
            'x-ratelimit-reset-requests': 'reset_requests',
            'x-ratelimit-reset-tokens': 'reset_tokens',
            'x-ratelimit-limit-requests': 'limit_requests',
            'x-ratelimit-limit-tokens': 'limit_tokens',
        }

        rate_info = {}

        for header_name, key_name in required_headers.items():
            header_value = headers.get(header_name)

            if header_value is None:
                raise ValueError(
                    f"Rate limit header '{header_name}' missing from OpenAI response. "
                    "This generator requires rate limit headers to function. "
                    "If the OpenAI API is not returning these headers, use the standard "
                    "'openai' generator instead."
                )

            # Parse based on expected type
            if 'reset' in key_name:
                # Reset headers are time strings like "6m0s"
                try:
                    rate_info[key_name] = _parse_time_string(header_value)
                except ValueError as e:
                    raise ValueError(
                        f"Invalid format for header '{header_name}': {header_value}"
                    ) from e
            else:
                # Remaining and limit headers are integers
                try:
                    rate_info[key_name] = int(header_value)
                except (ValueError, TypeError) as e:
                    raise ValueError(
                        f"Invalid format for header '{header_name}': {header_value}"
                    ) from e

        return rate_info

    def _check_and_wait_if_needed(self, rate_info: dict) -> None:
        """Check rate limit thresholds and pause if within safety margin.

        Monitors both request and token limits. If either drops below 5% remaining
        capacity (95% utilized), pauses execution until the corresponding limit resets.

        Uses the more restrictive limit (whichever is closer to exhaustion) to
        determine wait time.

        Args:
            rate_info: Parsed rate limit information from headers
        """
        # Calculate remaining capacity percentages
        requests_remaining_pct = (
            rate_info['remaining_requests'] / rate_info['limit_requests']
            if rate_info['limit_requests'] > 0 else 1.0
        )

        tokens_remaining_pct = (
            rate_info['remaining_tokens'] / rate_info['limit_tokens']
            if rate_info['limit_tokens'] > 0 else 1.0
        )

        # Check if either limit is below threshold
        requests_critical = requests_remaining_pct < self.RATE_LIMIT_THRESHOLD
        tokens_critical = tokens_remaining_pct < self.RATE_LIMIT_THRESHOLD

        if not (requests_critical or tokens_critical):
            # All clear - no rate limiting needed
            return

        # Determine which limit to wait for (use the more restrictive one)
        if requests_critical and tokens_critical:
            # Both critical - wait for whichever resets first
            if rate_info['reset_requests'] <= rate_info['reset_tokens']:
                limit_type = "requests"
                wait_time = rate_info['reset_requests']
                remaining_pct = requests_remaining_pct
                remaining_count = rate_info['remaining_requests']
                limit_count = rate_info['limit_requests']
            else:
                limit_type = "tokens"
                wait_time = rate_info['reset_tokens']
                remaining_pct = tokens_remaining_pct
                remaining_count = rate_info['remaining_tokens']
                limit_count = rate_info['limit_tokens']
        elif requests_critical:
            limit_type = "requests"
            wait_time = rate_info['reset_requests']
            remaining_pct = requests_remaining_pct
            remaining_count = rate_info['remaining_requests']
            limit_count = rate_info['limit_requests']
        else:  # tokens_critical
            limit_type = "tokens"
            wait_time = rate_info['reset_tokens']
            remaining_pct = tokens_remaining_pct
            remaining_count = rate_info['remaining_tokens']
            limit_count = rate_info['limit_tokens']

        # Add buffer and ensure non-negative
        wait_time_buffered = max(0, wait_time) + self.RESET_WAIT_BUFFER_SECONDS

        # Log rate limit warning
        logging.info(
            f"⚠️  OpenAI rate limit approaching: {remaining_pct:.1%} {limit_type} remaining "
            f"({remaining_count}/{limit_count})"
        )
        logging.info(
            f"⏸️  Pausing for {wait_time_buffered:.1f}s until {limit_type} rate limit resets "
            f"(reset in {wait_time:.1f}s + {self.RESET_WAIT_BUFFER_SECONDS}s buffer)"
        )

        # Pause execution
        time.sleep(wait_time_buffered)

        logging.info(f"▶️  Resuming operations after rate limit wait")

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
        """Call OpenAI API with rate limit monitoring.

        This method wraps the parent's _call_model to inject rate limit handling:
        1. Calls OpenAI API using with_raw_response to capture headers
        2. Parses rate limit headers from response
        3. Checks if approaching rate limits (< 5% remaining)
        4. Pauses if needed until rate limit resets
        5. Returns parsed response maintaining parent interface

        Args:
            prompt: Conversation or list of message dicts to send to model
            generations_this_call: Number of generations to request

        Returns:
            List of Message objects (or None for failed generations)

        Raises:
            ValueError: If rate limit headers are missing from response
            Other exceptions: Passed through from parent implementation
        """
        if self.client is None:
            # reload client once when consuming the generator
            self._load_client()

        # Build create_args exactly as parent does (copied from OpenAICompatible._call_model)
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
                # should this still be supported?
                messages = prompt
            else:
                msg = (
                    f"Expected a Conversation or list of dicts for {self.generator_family_name} Chat model {self.name}, but got {type(prompt)} instead. "
                    f"Returning nothing!"
                )
                logging.error(msg)
                return list()

            create_args["messages"] = messages

        # MODIFIED: Use with_raw_response to capture headers
        try:
            raw_response = self.generator.with_raw_response.create(**create_args)

            # Extract headers and parse rate limit information
            headers = raw_response.headers
            rate_info = self._parse_rate_limit_headers(headers)

            # Check thresholds and wait if needed
            self._check_and_wait_if_needed(rate_info)

            # Parse the actual response
            response = raw_response.parse()

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

        # Same response processing as parent
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
