"""Live wiring checks for source-bound YAML confirmation and concurrent edits."""

import asyncio
import uuid
from typing import Any

import pytest

from ...utilities.assertions import MCPAssertions, safe_call_tool
from .test_yaml_config import READ_TOOL, TOOL_NAME, call_set_yaml_confirmed
from .test_yaml_config import mcp_client_with_yaml_config as mcp_client_with_yaml_config
from .test_yaml_config import yaml_config_tools_enabled as yaml_config_tools_enabled

pytestmark = [pytest.mark.requires_tools_entry, pytest.mark.filesystem]


class TestYamlConfirmationSafety:
    @pytest.mark.parametrize("action", ["replace", "remove"])
    async def test_intervening_theme_edit_invalidates_confirmation(
        self, mcp_client_with_yaml_config: Any, action: str
    ) -> None:
        fname = f"themes/confirm_concurrent_{uuid.uuid4().hex[:8]}.yaml"
        theme = "Confirmation Probe"
        args = {"file": fname, "yaml_path": theme, "action": action}
        if action == "replace":
            args["content"] = "marker: requested\n"
        try:
            async with MCPAssertions(mcp_client_with_yaml_config) as mcp:
                await call_set_yaml_confirmed(
                    mcp,
                    {
                        "file": fname,
                        "yaml_path": theme,
                        "action": "add",
                        "content": "marker: unchanged\n",
                    },
                )
                preview = await mcp.call_tool_success(TOOL_NAME, args)
                assert preview["written"] is False, preview

                intervening = f"{theme}:\n  marker: unchanged # concurrent edit\n"
                await mcp.call_tool_success(
                    "ha_write_file",
                    {"path": fname, "content": intervening, "overwrite": True},
                )
                stale = await mcp.call_tool_success(
                    TOOL_NAME, {**args, "confirm_token": preview["confirm_token"]}
                )
                assert stale["written"] is False, stale
                assert stale["confirm_token_mismatch"] is True, stale
                assert stale["confirm_token"] != preview["confirm_token"]
                current = await mcp.call_tool_success(READ_TOOL, {"path": fname})
                assert current["content"] == intervening

                confirmed = await mcp.call_tool_success(
                    TOOL_NAME, {**args, "confirm_token": stale["confirm_token"]}
                )
                assert confirmed["written"] is True, confirmed
                assert confirmed["config_check"] == "ok", confirmed
        finally:
            await safe_call_tool(
                mcp_client_with_yaml_config,
                "ha_delete_file",
                {"path": fname, "confirm": True},
            )
            await safe_call_tool(
                mcp_client_with_yaml_config, "ha_reload_core", {"target": "themes"}
            )

    async def test_line_ending_change_invalidates_confirmation(
        self, mcp_client_with_yaml_config: Any
    ) -> None:
        fname = f"themes/confirm_newlines_{uuid.uuid4().hex[:8]}.yaml"
        original = "Confirmation Probe:\n  marker: unchanged\n"
        args = {
            "file": fname,
            "yaml_path": "Confirmation Probe",
            "action": "replace",
            "content": "marker: requested\n",
        }
        try:
            async with MCPAssertions(mcp_client_with_yaml_config) as mcp:
                await mcp.call_tool_success(
                    "ha_write_file", {"path": fname, "content": original}
                )
                preview = await mcp.call_tool_success(TOOL_NAME, args)
                changed = original.replace("\n", "\r\n")
                await mcp.call_tool_success(
                    "ha_write_file",
                    {"path": fname, "content": changed, "overwrite": True},
                )
                stale = await mcp.call_tool_success(
                    TOOL_NAME, {**args, "confirm_token": preview["confirm_token"]}
                )
                assert stale["written"] is False, stale
                assert stale["confirm_token_mismatch"] is True, stale
                assert stale["confirm_token"] != preview["confirm_token"]
                current = await mcp.call_tool_success(READ_TOOL, {"path": fname})
                assert current["size"] == len(changed.encode()), current
                assert current["content"].replace("\r\n", "\n") == original
                confirmed = await mcp.call_tool_success(
                    TOOL_NAME, {**args, "confirm_token": stale["confirm_token"]}
                )
                assert confirmed["written"] is True, confirmed
                assert confirmed["config_check"] == "ok", confirmed
        finally:
            await safe_call_tool(
                mcp_client_with_yaml_config,
                "ha_delete_file",
                {"path": fname, "confirm": True},
            )
            await safe_call_tool(
                mcp_client_with_yaml_config, "ha_reload_core", {"target": "themes"}
            )

    async def test_concurrent_confirmations_preserve_both_updates(
        self, mcp_client_with_yaml_config: Any
    ) -> None:
        fname = f"themes/confirm_parallel_{uuid.uuid4().hex[:8]}.yaml"
        themes = ("First Probe", "Second Probe")
        original = "First Probe: {marker: original}\nSecond Probe: {marker: original}\n"
        try:
            async with MCPAssertions(mcp_client_with_yaml_config) as mcp:
                await mcp.call_tool_success(
                    "ha_write_file", {"path": fname, "content": original}
                )
                requests = [
                    {
                        "file": fname,
                        "yaml_path": theme,
                        "action": "replace",
                        "content": f"marker: update_{index}\n",
                    }
                    for index, theme in enumerate(themes)
                ]
                for args in requests:
                    preview = await mcp.call_tool_success(TOOL_NAME, args)
                    args["confirm_token"] = preview["confirm_token"]
                results = await asyncio.gather(
                    *(mcp.call_tool_success(TOOL_NAME, args) for args in requests)
                )
                assert sorted(result["written"] for result in results) == [
                    False,
                    True,
                ], results
                for args, result in zip(requests, results, strict=True):
                    if not result["written"]:
                        assert result["confirm_token_mismatch"] is True, result
                        args["confirm_token"] = result["confirm_token"]
                        done = await mcp.call_tool_success(TOOL_NAME, args)
                        assert done["written"] is True, done
                        assert done["config_check"] == "ok", done
                current = await mcp.call_tool_success(READ_TOOL, {"path": fname})
                assert "update_0" in current["content"], current
                assert "update_1" in current["content"], current
        finally:
            await safe_call_tool(
                mcp_client_with_yaml_config,
                "ha_delete_file",
                {"path": fname, "confirm": True},
            )
            await safe_call_tool(
                mcp_client_with_yaml_config, "ha_reload_core", {"target": "themes"}
            )
