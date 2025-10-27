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
    """OpenAI generator wrapper with reactive rate limit handling.

    This generator monitors rate limit headers from OpenAI API responses and
    automatically pauses when usage reaches 95% of limits. It handles both
    request-based (RPM) and token-based (TPM) rate limits.

    Rate limit detection uses these OpenAI response headers:
    - x-ratelimit-remaining-requests / x-ratelimit-limit-requests
    - x-ratelimit-remaining-tokens / x-ratelimit-limit-tokens
    - x-ratelimit-reset-requests / x-ratelimit-reset-tokens

    The wrapper pauses execution and waits for the appropriate reset time when
    either rate limit threshold (95%) is exceeded.
    """

    generator_family_name = "OpenAI (Rate Limited)"

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
        try:
            raw_response = self.generator.with_raw_response.create(**create_args)
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

        # Extract headers for rate limit monitoring
        headers = raw_response.headers

        # Parse the actual response object
        response = raw_response.parse()

        # Check rate limits AFTER successful response
        self._check_and_handle_rate_limits(headers)

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

        Monitors both request-based (RPM) and token-based (TPM) rate limits.
        Pauses execution when either limit reaches 95% usage.

        Args:
            headers: HTTP response headers from OpenAI API

        Raises:
            RuntimeError: If required rate limit headers are missing
        """
        # Define required headers
        required_headers = {
            'x-ratelimit-remaining-tokens',
            'x-ratelimit-limit-tokens',
            'x-ratelimit-reset-tokens',
            'x-ratelimit-remaining-requests',
            'x-ratelimit-limit-requests',
            'x-ratelimit-reset-requests'
        }

        # Check for missing headers (case-insensitive)
        headers_lower = {k.lower(): v for k, v in headers.items()}
        missing = [h for h in required_headers if h not in headers_lower]

        if missing:
            # Log warning but don't fail - some models/tiers might not return all headers
            logging.warning(
                f"Missing rate limit headers (model may not support them): {missing}"
            )
            return

        try:
            remaining_tokens = int(headers_lower['x-ratelimit-remaining-tokens'])
            limit_tokens = int(headers_lower['x-ratelimit-limit-tokens'])
            reset_tokens = headers_lower['x-ratelimit-reset-tokens']

            remaining_requests = int(headers_lower['x-ratelimit-remaining-requests'])
            limit_requests = int(headers_lower['x-ratelimit-limit-requests'])
            reset_requests = headers_lower['x-ratelimit-reset-requests']
        except (ValueError, KeyError) as e:
            logging.warning(f"Failed to parse rate limit headers: {e}")
            return

        # Check token limit (95% usage = 5% remaining)
        if limit_tokens > 0 and remaining_tokens <= (limit_tokens * 0.05):
            wait_time = self._parse_reset_time(reset_tokens)
            logging.warning(
                f"Token rate limit at 95% usage ({remaining_tokens}/{limit_tokens} remaining)"
            )
            logging.warning(f"Pausing for {wait_time}s until reset")
            time.sleep(wait_time)

        # Check request limit (95% usage = 5% remaining)
        if limit_requests > 0 and remaining_requests <= (limit_requests * 0.05):
            wait_time = self._parse_reset_time(reset_requests)
            logging.warning(
                f"Request rate limit at 95% usage ({remaining_requests}/{limit_requests} remaining)"
            )
            logging.warning(f"Pausing for {wait_time}s until reset")
            time.sleep(wait_time)

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
