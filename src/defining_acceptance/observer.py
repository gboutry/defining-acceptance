"""Optional Test Observer integration.

When the ``TO_URL`` environment variable is set, this module registers a pytest
plugin that reports the test run and individual results to the Test Observer
REST API.

One test execution is created per category (Security, Reliability, Functional, …)
the first time a test from that category is encountered.  The execution's test
plan is named ``<TO_TEST_PLAN>-<category>`` (e.g. ``sunbeam-acceptance-security``).

Required environment variables (when ``TO_URL`` is set):
    TO_URL              Base URL of the Test Observer API.
    TO_SNAP_REVISION    Snap revision number (integer).

Optional environment variables:
    TO_SNAP_NAME        Snap name (default: ``openstack``).
    TO_SNAP_TRACK       Snap track (default: ``2024.1``).
    TO_SNAP_STAGE       Snap risk level: edge/beta/candidate/stable (default: ``edge``).
    TO_SNAP_VERSION     Version string (default: ``<track>/<stage>``).
    TO_SNAP_STORE       Snap store (default: ``ubuntu``).
    TO_ENVIRONMENT      Environment name (default: ``manual``).
    TO_TEST_PLAN        Test plan prefix (default: ``sunbeam-acceptance``).
    TO_ARCH             Architecture override (auto-detected if not set).
    TO_CI_LINK          URL of the CI job driving this run.
"""

from __future__ import annotations

import json
import logging
import os
import platform
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("defining_acceptance.observer")

_PLAN_TAGS = frozenset({"security", "reliability", "functional", "performance"})

_ARCH_MAP: dict[str, str] = {
    "x86_64": "amd64",
    "aarch64": "arm64",
    "armv7l": "armhf",
    "ppc64le": "ppc64el",
    "s390x": "s390x",
}


def _detect_arch() -> str:
    return _ARCH_MAP.get(platform.machine(), platform.machine())


class _BasePlugin:
    """Base class with shared pytest hooks for Test Observer plugins.

    Subclasses must implement :meth:`_ensure_category`, :meth:`_post_result`,
    and :meth:`_close_category`.
    """

    def __init__(
        self,
        make_body: Callable[[str], object],
        test_plan_prefix: str,
    ) -> None:
        # Callable(test_plan_name) -> StartSnapTestExecutionRequest
        self._make_body = make_body
        self._test_plan_prefix = test_plan_prefix
        # category (capitalised) -> backend-specific key (e.g. execution id or Path)
        self._executions: dict[str, Any] = {}
        # categories that had at least one failure (for final status)
        self._category_failed: set[str] = set()
        # pytest nodeids already reported (to avoid duplicate from setup+call)
        self._settled: set[str] = set()
        # per-test SSH output accumulator
        self._io_lines: list[str] = []
        # category for the currently running item (set from pytest markers)
        self._current_category: str = ""
        self._current_key: Any = None

        # Intercept report.attach_text / attach_file so every command output
        # that SSHRunner emits is also captured into _io_lines for io_log.
        from defining_acceptance.reporting import report as _report

        plugin = self

        _orig_text = _report.attach_text
        _orig_file = _report.attach_file

        def _capture_text(content: str, name: str) -> None:
            _orig_text(content, name)
            text = "" if content is None else str(content)
            if text.strip():
                plugin._io_lines.append(
                    f"===== BEGIN {name} =====\n{text}\n===== END {name} ====="
                )

        def _capture_file(path: object, name: str) -> None:
            _orig_file(path, name)
            try:
                text = Path(str(path)).read_text(encoding="utf-8", errors="replace")
                if text.strip():
                    plugin._io_lines.append(
                        f"===== BEGIN {name} =====\n{text}\n===== END {name} ====="
                    )
            except Exception:
                pass

        _report.attach_text = _capture_text  # type: ignore[method-assign]
        _report.attach_file = _capture_file  # type: ignore[method-assign]

    # ── Template methods ───────────────────────────────────────────────────────

    def _ensure_category(self, category: str) -> Any | None:
        """Return a backend key for *category*, creating one if needed.

        Returns ``None`` on error.
        """
        raise NotImplementedError

    def _post_result(self, key: Any, result: object) -> None:
        """Post a single test result associated with *key*."""
        raise NotImplementedError

    def _close_category(self, category: str, key: Any, status: object) -> None:
        """Close/finalise the execution associated with *key*."""
        raise NotImplementedError

    def _post_event(
        self, key: Any, event_name: str, detail: str, timestamp: object
    ) -> None:
        """Post an event."""
        raise NotImplementedError

    # ── Pytest hooks ──────────────────────────────────────────────────────────

    def pytest_runtest_setup(self, item: object) -> None:
        """Reset per-test state, extract category, and register the step hook."""
        # Always clear state from the previous test first.
        self._io_lines = []
        self._current_category = ""
        self._current_key = None
        from defining_acceptance.reporting import report as _report

        _report.set_event_callback(None)

        get_marker = getattr(item, "get_closest_marker", None)
        if get_marker is None:
            return
        for tag in _PLAN_TAGS:
            if get_marker(tag) is not None:
                self._current_category = tag.capitalize()
                break

        if not self._current_category:
            return

        key = self._ensure_category(self._current_category)
        if key is None:
            return
        self._current_key = key

        plugin = self

        def _on_event(event_name: str, detail: str, timestamp: object) -> None:
            plugin._post_event(key, event_name, detail, timestamp)

        _report.set_event_callback(_on_event)

    def pytest_runtest_logreport(self, report: object) -> None:
        from defining_acceptance.clients.test_observer_client.models.test_result_request import (
            TestResultRequest,
        )
        from defining_acceptance.clients.test_observer_client.models.test_result_status import (
            TestResultStatus,
        )

        when = getattr(report, "when", None)
        # Use the raw pytest nodeid for dedup tracking (guaranteed unique).
        pytest_nodeid = getattr(report, "nodeid", "")

        # Category is derived from pytest markers in pytest_runtest_setup,
        # which is guaranteed to match the same marker set used by skip rules.
        category = self._current_category
        if not category:
            return  # skip non-BDD or uncategorised tests

        # Human-readable name: scenario title when available, nodeid otherwise.
        name = pytest_nodeid
        if scenario := getattr(report, "scenario", None):
            name = scenario["name"]

        key = self._current_key
        if key is None:
            return

        longrepr = getattr(report, "longrepr", None)
        io_log = str(longrepr) if longrepr else ""
        if self._io_lines:
            io_log += "\n\n" if io_log else ""
            io_log += "\n\n".join(self._io_lines)

        if when == "setup":
            if getattr(report, "failed", False):
                self._settled.add(pytest_nodeid)
                self._category_failed.add(category)
                self._post_result(
                    key,
                    TestResultRequest(
                        name=name,
                        status=TestResultStatus.FAILED,
                        category=category,
                        io_log=io_log,
                    ),
                )
            elif getattr(report, "skipped", False):
                self._settled.add(pytest_nodeid)
                self._post_result(
                    key,
                    TestResultRequest(
                        name=name,
                        status=TestResultStatus.SKIPPED,
                        category=category,
                        io_log=io_log,
                    ),
                )
            # setup passed → wait for the call phase

        elif when == "call":
            if pytest_nodeid in self._settled:
                return  # already reported from setup
            if getattr(report, "passed", False):
                status = TestResultStatus.PASSED
            elif getattr(report, "failed", False):
                status = TestResultStatus.FAILED
                self._category_failed.add(category)
            else:
                status = TestResultStatus.SKIPPED
            self._post_result(
                key,
                TestResultRequest(
                    name=name,
                    status=status,
                    category=category,
                    io_log=io_log,
                ),
            )

    def pytest_sessionfinish(self, session: object, exitstatus: int) -> None:
        from defining_acceptance.clients.test_observer_client.models.test_execution_status import (
            TestExecutionStatus,
        )

        interrupted = exitstatus == 2  # keyboard interrupt

        for category, key in self._executions.items():
            if interrupted:
                status = TestExecutionStatus.ENDED_PREMATURELY
            elif category in self._category_failed:
                status = TestExecutionStatus.FAILED
            else:
                status = TestExecutionStatus.PASSED

            self._close_category(category, key, status)


class TestObserverPlugin(_BasePlugin):
    """Pytest plugin that streams test results to the Test Observer API.

    One test execution is created per test category (plan tag) the first time
    a result for that category arrives.  All executions are closed together at
    session end.
    """

    def __init__(
        self,
        client: object,
        make_body: Callable[[str], object],
        test_plan_prefix: str,
    ) -> None:
        super().__init__(make_body=make_body, test_plan_prefix=test_plan_prefix)
        self._client = client

    # ── Template method implementations ───────────────────────────────────────

    def _ensure_category(self, category: str) -> int | None:
        """Return the execution id for *category*, creating one if needed."""
        if category in self._executions:
            return self._executions[category]

        from defining_acceptance.clients.test_observer_client.api.test_executions import (
            start_test_execution_v1_test_executions_start_test_put as start_api,
        )

        test_plan = f"{self._test_plan_prefix}-{category.lower()}"
        try:
            response = start_api.sync_detailed(
                client=self._client,
                body=self._make_body(test_plan),
            )
            logger.debug("Received response: %s", response)  # Debug statement
        except Exception:
            logger.warning(
                "Failed to start Test Observer execution for category %r",
                category,
                exc_info=True,
            )
            return None

        if not (200 <= response.status_code.value < 300):
            logger.warning(
                "start-test for category %r returned HTTP %d (body: %r)",
                category,
                response.status_code.value,
                response.content[:200],
            )
            return None

        try:
            data = json.loads(response.content)
            execution_id = data["id"]
        except Exception:
            logger.warning(
                "Could not parse execution id for category %r from: %r",
                category,
                response.content,
            )
            return None

        self._executions[category] = execution_id
        logger.info(
            "Test Observer: started execution id=%d plan=%r",
            execution_id,
            test_plan,
        )
        return execution_id

    def _post_result(self, execution_id: int, result: object) -> None:
        from defining_acceptance.clients.test_observer_client.api.test_executions import (
            post_results_v1_test_executions_id_test_results_post as post_api,
        )

        try:
            post_api.sync(execution_id, client=self._client, body=[result])
        except Exception:
            name = getattr(result, "name", repr(result))
            logger.warning("Failed to post result(s) for %s", name, exc_info=True)

    def _close_category(self, category: str, execution_id: int, status: object) -> None:
        from defining_acceptance.clients.test_observer_client.api.test_executions import (
            patch_test_execution_v1_test_executions_id_patch as patch_api,
        )
        from defining_acceptance.clients.test_observer_client.models.test_executions_patch_request import (
            TestExecutionsPatchRequest,
        )

        try:
            patch_api.sync(
                execution_id,
                client=self._client,
                body=TestExecutionsPatchRequest(status=status),
            )
            logger.info(
                "Test Observer: closed execution id=%d (category=%r) status=%s",
                execution_id,
                category,
                status.value,
            )
        except Exception:
            logger.warning(
                "Failed to close Test Observer execution %d (category=%r)",
                execution_id,
                category,
                exc_info=True,
            )

    def _post_event(
        self, key: Any, event_name: str, detail: str, timestamp: object
    ) -> None:
        execution_id = key
        from defining_acceptance.clients.test_observer_client.api.test_executions import (
            post_status_update_v1_test_executions_id_status_update_post as status_api,
        )
        from defining_acceptance.clients.test_observer_client.models.status_update_request import (
            StatusUpdateRequest,
        )
        from defining_acceptance.clients.test_observer_client.models.test_event_response import (
            TestEventResponse,
        )

        try:
            status_api.sync(
                execution_id,
                client=self._client,
                body=StatusUpdateRequest(
                    events=[
                        TestEventResponse(
                            event_name=event_name,
                            timestamp=timestamp,
                            detail=detail,
                        )
                    ]
                ),
            )
        except Exception:
            logger.warning(
                "Failed to post status update %r for execution %d",
                detail,
                execution_id,
                exc_info=True,
            )


class DeferredPlugin(_BasePlugin):
    """Pytest plugin that writes test results to disk for later upload.

    One subdirectory is created per test category.  Each subdirectory contains:
    - ``start.json``   — the request body that would be sent to start-test
    - ``results.jsonl`` — one JSON object per line, one per test result
    - ``patch.json``   — the PATCH request body to close the execution
    """

    def __init__(
        self,
        output_dir: Path,
        make_body: Callable[[str], object],
        test_plan_prefix: str,
    ) -> None:
        super().__init__(make_body=make_body, test_plan_prefix=test_plan_prefix)
        self._output_dir = output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

    # ── Template method implementations ───────────────────────────────────────

    def _ensure_category(self, category: str) -> Path | None:
        """Return the category directory for *category*, creating it if needed."""
        if category in self._executions:
            return self._executions[category]

        test_plan = f"{self._test_plan_prefix}-{category.lower()}"
        cat_dir = self._output_dir / category.lower()
        try:
            cat_dir.mkdir(parents=True, exist_ok=True)
            start_data = self._make_body(test_plan).to_dict()
            (cat_dir / "start.json").write_text(
                json.dumps(start_data, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.warning(
                "Failed to initialise deferred directory for category %r",
                category,
                exc_info=True,
            )
            return None

        self._executions[category] = cat_dir
        logger.info(
            "Deferred: initialised category %r at %s",
            category,
            cat_dir,
        )
        return cat_dir

    def _post_result(self, cat_dir: Path, result: object) -> None:
        try:
            with (cat_dir / "results.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(result.to_dict()) + "\n")
        except Exception:
            name = getattr(result, "name", repr(result))
            logger.warning(
                "Failed to write deferred result for %s", name, exc_info=True
            )

    def _close_category(self, category: str, cat_dir: Path, status: object) -> None:
        from defining_acceptance.clients.test_observer_client.models.test_executions_patch_request import (
            TestExecutionsPatchRequest,
        )

        try:
            patch_body = TestExecutionsPatchRequest(status=status)
            (cat_dir / "patch.json").write_text(
                json.dumps(patch_body.to_dict(), indent=2), encoding="utf-8"
            )
            logger.info(
                "Deferred: wrote patch.json for category %r status=%s",
                category,
                status.value,
            )
        except Exception:
            logger.warning(
                "Failed to write deferred patch.json for category %r",
                category,
                exc_info=True,
            )

    def _post_event(
        self, key: Any, event_name: str, detail: str, timestamp: object
    ) -> None:
        cat_dir = key
        try:
            entry = {
                "event_name": event_name,
                "timestamp": timestamp.isoformat()
                if hasattr(timestamp, "isoformat")
                else str(timestamp),
                "detail": detail,
            }
            with (cat_dir / "status_updates.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception:
            logger.warning(
                "Failed to write deferred status update %r", detail, exc_info=True
            )


def create_plugin() -> TestObserverPlugin | DeferredPlugin | None:
    """Build a plugin from environment variables.

    Returns ``None`` (silently) when ``TO_URL`` is not set, or logs a warning
    and returns ``None`` when required variables are missing.

    When ``TO_URL`` starts with ``file://``, a :class:`DeferredPlugin` is
    returned that writes results to disk for later upload via ``to-upload``.
    No network call is made in either case at plugin creation time; executions
    are created lazily on first use per category.
    """
    to_url = os.environ.get("TO_URL")
    if not to_url:
        return None

    try:
        from defining_acceptance.clients.test_observer_client.models.snap_stage import (
            SnapStage,
        )
        from defining_acceptance.clients.test_observer_client.models.start_snap_test_execution_request import (
            StartSnapTestExecutionRequest,
        )
        from defining_acceptance.clients.test_observer_client.models.test_execution_relevant_link_create import (
            TestExecutionRelevantLinkCreate,
        )
        from defining_acceptance.clients.test_observer_client.models.test_execution_status import (
            TestExecutionStatus,
        )
        from defining_acceptance.clients.test_observer_client.types import UNSET
    except ImportError:
        logger.warning(
            "Test Observer dependencies not installed (httpx, attrs). "
            "Install the 'to' dependency group to enable TO reporting."
        )
        return None

    revision_str = os.environ.get("TO_SNAP_REVISION", "")
    if not revision_str:
        logger.warning("TO_SNAP_REVISION not set; Test Observer registration skipped")
        return None
    try:
        revision = int(revision_str)
    except ValueError:
        logger.warning(
            "TO_SNAP_REVISION=%r is not a valid integer; Test Observer registration skipped",
            revision_str,
        )
        return None

    snap_stage_str = os.environ.get("TO_SNAP_STAGE", "edge")
    try:
        snap_stage = SnapStage(snap_stage_str)
    except ValueError:
        logger.warning(
            "TO_SNAP_STAGE=%r is not valid (edge/beta/candidate/stable); "
            "Test Observer registration skipped",
            snap_stage_str,
        )
        return None

    snap_track = os.environ.get("TO_SNAP_TRACK", "2024.1")
    snap_name = os.environ.get("TO_SNAP_NAME", "openstack")
    snap_version = os.environ.get("TO_SNAP_VERSION") or f"{snap_track}/{snap_stage_str}"
    snap_store = os.environ.get("TO_SNAP_STORE", "ubuntu")
    environment = os.environ.get("TO_ENVIRONMENT", "manual")
    test_plan_prefix = os.environ.get("TO_TEST_PLAN", "sunbeam-acceptance")
    arch = os.environ.get("TO_ARCH") or _detect_arch()
    ci_link = os.environ.get("TO_CI_LINK") or None
    relevant_links = (
        [TestExecutionRelevantLinkCreate(label="CI job", url=ci_link)]
        if ci_link
        else UNSET
    )

    def make_body(test_plan: str) -> StartSnapTestExecutionRequest:
        local_ci_link = ci_link + "#" + test_plan if ci_link else UNSET
        return StartSnapTestExecutionRequest(
            name=snap_name,
            version=snap_version,
            arch=arch,
            environment=environment,
            test_plan=test_plan,
            initial_status=TestExecutionStatus.IN_PROGRESS,
            relevant_links=relevant_links,
            family="snap",
            revision=revision,
            track=snap_track,
            store=snap_store,
            execution_stage=snap_stage,
            ci_link=local_ci_link,
        )

    if to_url.startswith("file://"):
        output_dir = Path(to_url[len("file://") :])
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Test Observer: deferred mode, results will be written to %s",
            output_dir,
        )
        return DeferredPlugin(
            output_dir=output_dir,
            make_body=make_body,
            test_plan_prefix=test_plan_prefix,
        )
    else:
        from defining_acceptance.clients.test_observer_client import Client

        client = Client(base_url=to_url)
        logger.info(
            "Test Observer: configured, executions will be created per category at %s",
            to_url,
        )
        return TestObserverPlugin(
            client=client,
            make_body=make_body,
            test_plan_prefix=test_plan_prefix,
        )
