"""Regression coverage for coordinated component file mutations."""

import asyncio
import stat
import threading
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from . import test_yaml_edit_untouched_content as _yaml_fixtures

component = import_module("custom_components.ha_mcp_tools")

hass = _yaml_fixtures.hass
call_factory = _yaml_fixtures.call_factory
_stub_config_check = _yaml_fixtures._stub_config_check
CallFactory = Callable[[dict[str, Any]], MagicMock]


def edit_args(
    theme: str = "Theme A", file: str = "themes/shared.yaml"
) -> dict[str, Any]:
    return {
        "file": file,
        "yaml_path": theme,
        "action": "replace",
        "content": "marker: updated\n",
        "require_confirm": True,
    }


def seed(root: Path, name: str = "shared.yaml") -> Path:
    target = root / "themes" / name
    target.parent.mkdir(exist_ok=True)
    target.write_text("Theme A:\n  marker: original\nTheme B:\n  marker: original\n")
    return target


def pause_first_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[asyncio.Event, asyncio.Event]:
    entered, release = asyncio.Event(), asyncio.Event()
    real = component._serialize_and_validate_edit

    async def paused(*args: Any) -> Any:
        if not entered.is_set():
            entered.set()
            await release.wait()
        return await real(*args)

    monkeypatch.setattr(component, "_serialize_and_validate_edit", paused)
    return entered, release


@pytest.mark.parametrize(
    "alias", ["themes/shared.yaml", "themes/./shared.yaml", "themes/alias/shared.yaml"]
)
async def test_concurrent_confirmations_preserve_both_edits(
    tmp_path: Path,
    hass: MagicMock,
    call_factory: CallFactory,
    monkeypatch: pytest.MonkeyPatch,
    alias: str,
) -> None:
    target = seed(tmp_path)
    if "alias" in alias:
        (target.parent / "alias").symlink_to(target.parent, target_is_directory=True)
    first_handler = component._build_edit_yaml_config_handler(hass)
    second_handler = component._build_edit_yaml_config_handler(hass)
    first_args, second_args = edit_args(), edit_args("Theme B", alias)
    for handler, args in ((first_handler, first_args), (second_handler, second_args)):
        args["confirm_token"] = (await handler(call_factory(args)))["confirm_token"]
    entered, release = pause_first_serialization(monkeypatch)
    first = asyncio.create_task(first_handler(call_factory(first_args)))
    await entered.wait()
    second = asyncio.create_task(second_handler(call_factory(second_args)))
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(first, second)
    assert [r["written"] for r in results] == [True, False], results
    assert results[1]["confirm_token_mismatch"] is True
    second_args["confirm_token"] = results[1]["confirm_token"]
    assert (await second_handler(call_factory(second_args)))["written"] is True
    data = component.make_yaml().load(target.read_text())
    assert data["Theme A"]["marker"] == data["Theme B"]["marker"] == "updated"


async def test_different_files_can_progress_independently(
    tmp_path: Path,
    hass: MagicMock,
    call_factory: CallFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed(tmp_path)
    seed(tmp_path, "other.yaml")
    handler = component._build_edit_yaml_config_handler(hass)
    first_args, second_args = edit_args(), edit_args(file="themes/other.yaml")
    for args in (first_args, second_args):
        args["confirm_token"] = (await handler(call_factory(args)))["confirm_token"]
    entered, release = pause_first_serialization(monkeypatch)
    first = asyncio.create_task(handler(call_factory(first_args)))
    await entered.wait()
    try:
        result = await asyncio.wait_for(handler(call_factory(second_args)), timeout=1)
        assert result["written"] is True
        assert not first.done()
    finally:
        release.set()
        await first


@pytest.mark.parametrize("operation", ["write", "delete", "restore"])
async def test_other_mutations_wait_for_yaml_edit(
    tmp_path: Path,
    hass: MagicMock,
    call_factory: CallFactory,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    target = seed(tmp_path)
    handler = component._build_edit_yaml_config_handler(hass)
    args = edit_args()
    args["confirm_token"] = (await handler(call_factory(args)))["confirm_token"]
    replacement = "Theme A:\n  marker: explicitly_replaced\n"
    if operation == "write":
        other = component._build_write_file_handler(hass)
        other_args = {"path": args["file"], "content": replacement, "overwrite": True}
    elif operation == "delete":
        other = component._build_delete_file_handler(hass)
        other_args = {"path": args["file"]}
    else:
        other = component._build_edit_yaml_config_handler(hass)
        other_args = {**args, "action": "replace_file", "content": replacement}
    entered, release = pause_first_serialization(monkeypatch)
    first = asyncio.create_task(handler(call_factory(args)))
    await entered.wait()
    second = asyncio.create_task(other(call_factory(other_args)))
    try:
        await asyncio.sleep(0)
        assert not second.done(), (
            "same-file mutation bypassed the YAML critical section"
        )
    finally:
        release.set()
        results = await asyncio.gather(first, second)
    assert all(r["success"] for r in results), results
    if operation == "delete":
        assert not target.exists()
    else:
        assert target.read_text() == replacement


async def test_external_change_during_serialization_is_not_overwritten(
    tmp_path: Path,
    hass: MagicMock,
    call_factory: CallFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = seed(tmp_path)
    handler = component._build_edit_yaml_config_handler(hass)
    args = edit_args()
    args["confirm_token"] = (await handler(call_factory(args)))["confirm_token"]
    entered, release = pause_first_serialization(monkeypatch)
    task = asyncio.create_task(handler(call_factory(args)))
    await entered.wait()
    changed = "Theme A:\n  marker: external\n"
    target.write_text(changed)
    release.set()
    result = await task
    assert result["success"] is False, result
    assert result["written"] is False, result
    assert "changed" in result["error"].lower()
    assert target.read_text() == changed
    assert list(target.parent.iterdir()) == [target]
    hass.services.async_call.assert_not_called()


@pytest.mark.parametrize("operation", ["write", "delete", "restore", "yaml"])
@pytest.mark.parametrize("worker_fails", [False, True])
async def test_cancelled_write_keeps_lock_until_executor_finishes(
    tmp_path: Path,
    hass: MagicMock,
    call_factory: CallFactory,
    operation: str,
    worker_fails: bool,
) -> None:
    target = seed(tmp_path)
    loop = asyncio.get_running_loop()
    started, second_started = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    writes = 0
    if operation == "write":
        first_handler = component._build_write_file_handler(hass)
        first_args = {
            "path": "themes/shared.yaml",
            "content": "first",
            "overwrite": True,
        }
    elif operation == "delete":
        first_handler = component._build_delete_file_handler(hass)
        first_args = {"path": "themes/shared.yaml"}
    else:
        first_handler = component._build_edit_yaml_config_handler(hass)
        first_args = edit_args()
        if operation == "restore":
            first_args.update(
                action="replace_file", content="Theme A: {marker: first}\n"
            )
        else:
            first_args["confirm_token"] = (
                await first_handler(call_factory(first_args))
            )["confirm_token"]

    def execute(fn: Callable[..., Any], *args: Any) -> asyncio.Future[Any]:
        nonlocal writes
        if fn in (
            component._write_file_sync,
            component._delete_file_sync,
            component._replace_file_sync,
        ):
            writes += 1
            if writes == 1:

                def blocked() -> Any:
                    loop.call_soon_threadsafe(started.set)
                    assert release.wait(timeout=5), "test failed to release writer"
                    if worker_fails:
                        raise OSError("injected executor failure after cancellation")
                    return fn(*args)

                return loop.run_in_executor(None, blocked)
            second_started.set()
        result = loop.create_future()
        result.set_result(fn(*args))
        return result

    hass.async_add_executor_job = execute
    handler = component._build_write_file_handler(hass)
    first = asyncio.create_task(first_handler(call_factory(first_args)))
    await started.wait()
    first.cancel()
    await asyncio.sleep(0)
    second = asyncio.create_task(
        handler(
            call_factory(
                {"path": "themes/shared.yaml", "content": "second", "overwrite": True}
            )
        )
    )
    try:
        first.cancel()  # Cleanup must withstand repeated cancellation too.
        await asyncio.sleep(0)
        assert not first.done(), "lock released while its executor write was running"
        assert not second_started.is_set()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert (await second)["success"] is True
    assert target.read_text() == "second"


async def test_cancelled_waiter_does_not_write_or_poison_lock(
    tmp_path: Path,
    hass: MagicMock,
    call_factory: CallFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = seed(tmp_path)
    handler = component._build_edit_yaml_config_handler(hass)
    first_args, second_args = edit_args(), edit_args("Theme B")
    for args in (first_args, second_args):
        args["confirm_token"] = (await handler(call_factory(args)))["confirm_token"]
    entered, release = pause_first_serialization(monkeypatch)
    first = asyncio.create_task(handler(call_factory(first_args)))
    await entered.wait()
    second = asyncio.create_task(handler(call_factory(second_args)))
    await asyncio.sleep(0)
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second
    release.set()
    assert (await first)["written"] is True
    current = component.make_yaml().load(target.read_text())
    assert current["Theme A"]["marker"] == "updated"
    assert current["Theme B"]["marker"] == "original"
    preview = await asyncio.wait_for(handler(call_factory(second_args)), timeout=1)
    assert preview["confirm_token_mismatch"] is True
    second_args["confirm_token"] = preview["confirm_token"]
    assert (await handler(call_factory(second_args)))["written"] is True


async def test_failed_write_releases_lock_and_preserves_file(
    tmp_path: Path,
    hass: MagicMock,
    call_factory: CallFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = seed(tmp_path)
    original = target.read_bytes()
    handler = component._build_edit_yaml_config_handler(hass)
    args = edit_args()
    args["confirm_token"] = (await handler(call_factory(args)))["confirm_token"]
    real_replace = component.os.replace
    calls = 0

    def fail_once(*args: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected write failure")
        return real_replace(*args)

    monkeypatch.setattr(component.os, "replace", fail_once)
    assert (await handler(call_factory(args)))["success"] is False
    assert target.read_bytes() == original
    assert list(target.parent.iterdir()) == [target]
    result = await asyncio.wait_for(handler(call_factory(args)), timeout=1)
    assert result["written"] is True


def test_restore_uses_unique_temporary_file_and_preserves_mode(tmp_path: Path) -> None:
    target = seed(tmp_path)
    target.chmod(0o640)
    unrelated = target.with_suffix(".tmp")
    unrelated.write_text("do not overwrite")
    component._replace_file_sync(target, "restored: yes\n")
    assert unrelated.read_text() == "do not overwrite"
    assert target.read_text() == "restored: yes\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert set(target.parent.iterdir()) == {target, unrelated}
