"""Tests for slash commands handled in AgentLoop."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.config.schema import CLIRunnerConfig


def _make_loop(cli_runners=None):
    """Create a minimal AgentLoop with mocked dependencies."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager"):
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace, cli_runners=cli_runners)
    return loop, bus


class TestRestartCommand:

    @pytest.mark.asyncio
    async def test_restart_sends_message_and_calls_execv(self):
        loop, bus = _make_loop()
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/restart")

        with patch("nanobot.agent.loop.os.execv") as mock_execv:
            await loop._handle_restart(msg)
            out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
            assert "Restarting" in out.content

            await asyncio.sleep(1.5)
            mock_execv.assert_called_once()

    @pytest.mark.asyncio
    async def test_restart_intercepted_in_run_loop(self):
        """Verify /restart is handled at the run-loop level, not inside _dispatch."""
        loop, bus = _make_loop()
        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/restart")

        with patch.object(loop, "_handle_restart") as mock_handle:
            mock_handle.return_value = None
            await bus.publish_inbound(msg)

            loop._running = True
            run_task = asyncio.create_task(loop.run())
            await asyncio.sleep(0.1)
            loop._running = False
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass

            mock_handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_help_includes_restart(self):
        loop, bus = _make_loop()
        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/help")

        response = await loop._process_message(msg)

        assert response is not None
        assert "/restart" in response.content
        assert "/codex <prompt>" in response.content
        assert "/gemini <prompt>" in response.content
        assert "/qwen <prompt>" in response.content
        assert "/codefree <prompt>" in response.content


class TestCodexCommand:

    @pytest.mark.asyncio
    async def test_codex_command_runs_local_exec(self):
        loop, _ = _make_loop()
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/codex fix the failing test")

        with patch.object(loop, "_run_cli_runner", new=AsyncMock(return_value="fixed")) as mock_run:
            response = await loop._process_message(msg)

        assert response is not None
        assert response.content == "fixed"
        mock_run.assert_awaited_once_with("codex", "fix the failing test")

    @pytest.mark.asyncio
    async def test_plain_codex_prefix_runs_local_exec(self):
        loop, _ = _make_loop()
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="codex summarize this repo")

        with patch.object(loop, "_run_cli_runner", new=AsyncMock(return_value="summary")) as mock_run:
            response = await loop._process_message(msg)

        assert response is not None
        assert response.content == "summary"
        mock_run.assert_awaited_once_with("codex", "summarize this repo")

    @pytest.mark.asyncio
    async def test_codex_command_requires_prompt(self):
        loop, _ = _make_loop()
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/codex")

        response = await loop._process_message(msg)

        assert response is not None
        assert response.content == "Usage: /codex <prompt>"


class TestCliRunners:

    @pytest.mark.asyncio
    async def test_builtin_qwen_runner_dispatches(self):
        loop, _ = _make_loop()
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/qwen explain this repo")

        with patch.object(loop, "_run_cli_runner", new=AsyncMock(return_value="qwen-summary")) as mock_run:
            response = await loop._process_message(msg)

        assert response is not None
        assert response.content == "qwen-summary"
        mock_run.assert_awaited_once_with("qwen", "explain this repo")

    @pytest.mark.asyncio
    async def test_custom_cli_runner_dispatches(self):
        loop, _ = _make_loop(
            cli_runners={
                "demo": CLIRunnerConfig(
                    command="demo-cli",
                    args=["--prompt", "{prompt}"],
                    description="Run demo CLI",
                )
            }
        )
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/demo say hello")

        with patch.object(loop, "_run_cli_runner", new=AsyncMock(return_value="demo-output")) as mock_run:
            response = await loop._process_message(msg)

        assert response is not None
        assert response.content == "demo-output"
        mock_run.assert_awaited_once_with("demo", "say hello")

    @pytest.mark.asyncio
    async def test_custom_cli_runner_help_entry(self):
        loop, _ = _make_loop(
            cli_runners={
                "demo": CLIRunnerConfig(
                    command="demo-cli",
                    args=["--prompt", "{prompt}"],
                    description="Run demo CLI",
                )
            }
        )
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/help")

        response = await loop._process_message(msg)

        assert response is not None
        assert "/demo <prompt> — Run demo CLI" in response.content


class TestRunnerCwdCommand:

    @pytest.mark.asyncio
    async def test_runner_cwd_requires_args(self):
        loop, _ = _make_loop()
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/runner-cwd")

        response = await loop._process_message(msg)

        assert response is not None
        assert response.content == "Usage: /runner-cwd <runner> <cwd|default>"

    @pytest.mark.asyncio
    async def test_runner_cwd_updates_builtin_and_persists(self):
        loop, _ = _make_loop()
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/runner-cwd codex /tmp/codex-ws")

        loaded = MagicMock()
        loaded.tools.cli_runners = {}

        with patch("nanobot.config.loader.load_config", return_value=loaded), \
             patch("nanobot.config.loader.save_config") as mock_save:
            response = await loop._process_message(msg)

        assert response is not None
        assert response.content == "Updated `codex` cwd to `/tmp/codex-ws`. Effective immediately."
        assert loop._runner_value(loop._available_cli_runners()["codex"], "cwd") == "/tmp/codex-ws"
        assert loaded.tools.cli_runners["codex"].cwd == "/tmp/codex-ws"
        mock_save.assert_called_once_with(loaded)

    @pytest.mark.asyncio
    async def test_runner_cwd_default_falls_back_to_workspace(self):
        loop, _ = _make_loop()
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/runner-cwd codex default")

        loaded = MagicMock()
        loaded.tools.cli_runners = {}

        with patch("nanobot.config.loader.load_config", return_value=loaded), \
             patch("nanobot.config.loader.save_config"):
            response = await loop._process_message(msg)

        assert response is not None
        assert response.content == "Updated `codex` cwd to `{workspace}`. Effective immediately."
        assert loaded.tools.cli_runners["codex"].cwd is None

    @pytest.mark.asyncio
    async def test_runner_cwd_rejects_unknown_runner(self):
        loop, _ = _make_loop()
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/runner-cwd no-such /tmp/x")

        response = await loop._process_message(msg)

        assert response is not None
        assert response.content.startswith("Unknown CLI runner `no-such`.")
