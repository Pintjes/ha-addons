"""Tests of Voice Agent Bridge error handling (no Claude, no Home Assistant needed).

Run: python tests/voice_agent_bridge/test_gateway.py voice_agent_bridge
"""

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path

ADDON = Path(sys.argv.pop(1) if len(sys.argv) > 1 else "voice_agent_bridge").resolve()
TMP = Path(tempfile.mkdtemp())
os.environ["OPTIONS_FILE"] = str(TMP / "options.json")
os.environ["DATA_DIR"] = str(TMP)
sys.path.insert(0, str(ADDON))

import gateway  # noqa: E402

HA = "mcp__homeassistant__"


def make_run(events, returncode=0, stderr=""):
    run = gateway.Run()
    sent = []
    for ev in events:
        run.feed(ev, sent.append, {})
    run.returncode = returncode
    run.stderr = stderr
    return run


def tool_use(name, uid):
    return {"type": "assistant", "session_id": "s1",
            "message": {"content": [{"type": "tool_use", "id": uid, "name": name, "input": {}}]}}


def tool_error(uid, text):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": uid, "is_error": True,
         "content": [{"type": "text", "text": text}]}]}}


def text_delta(text):
    return {"type": "stream_event", "event": {"type": "content_block_delta",
                                              "delta": {"type": "text_delta", "text": text}}}


def result(is_error=False, subtype="success", **extra):
    ev = {"type": "result", "session_id": "s1", "is_error": is_error, "subtype": subtype,
          "num_turns": 3, "duration_ms": 4200}
    ev.update(extra)
    return ev


SUCCESS = [text_delta("La TV est allumée."), result(result="La TV est allumée.")]
FAILED_SEARCH = [tool_use(HA + "ha_search", "t1"),
                 tool_error("t1", "Invalid arguments: unexpected_keyword_argument"),
                 tool_use(HA + "ha_search", "t2"),
                 tool_error("t2", "Invalid arguments: unexpected_keyword_argument"),
                 result(is_error=True, subtype="error_during_execution")]


class Runner:
    """Plays prepared runs in order, as run_once would."""

    def __init__(self, *runs):
        self.runs = list(runs)
        self.calls = 0

    def __call__(self, prompt, resume, mcp_config, on_text):
        self.calls += 1
        events, rc, err = self.runs.pop(0)
        run = gateway.Run()
        for ev in events:
            run.feed(ev, on_text, {})
        run.returncode, run.stderr = rc, err
        return run


def ask(runner):
    spoken = []
    text, sid = gateway.run_claude("prompt", None, Path("mcp.json"), spoken.append, runner=runner)
    return text, sid, "".join(spoken)


class ErrorHandling(unittest.TestCase):
    def setUp(self):
        gateway.OPTIONS.update({"claude_token": "", "anthropic_api_key": "", "gateway_api_key": "",
                                "timeout": 90})

    def test_cause_logged_and_safe_retry(self):
        """The 18:12 case: refused ha_search calls, error without text, exit code 1."""
        runner = Runner((FAILED_SEARCH, 1, ""), (SUCCESS, 0, ""))
        with self.assertLogs("voice_agent_bridge", level="WARNING") as logs:
            text, sid, spoken = ask(runner)
        out = "\n".join(logs.output)
        self.assertIn("Tool refused or failed: ha_search: Invalid arguments: unexpected_keyword_argument", out)
        self.assertIn("Claude error: error_during_execution, exit code 1, 3 turn(s), 4.2 s; "
                      "tools called: ha_search, ha_search", out)
        self.assertIn("Trying the request once more", out)
        self.assertEqual(runner.calls, 2)
        self.assertEqual(text, "La TV est allumée.")
        self.assertEqual(spoken, "La TV est allumée.")

    def test_no_retry_after_an_action(self):
        events = [tool_use(HA + "ha_call_service", "t1"),
                  result(is_error=True, subtype="error_during_execution")]
        runner = Runner((events, 1, ""), (SUCCESS, 0, ""))
        with self.assertLogs("voice_agent_bridge", level="ERROR"):
            text, _, spoken = ask(runner)
        self.assertEqual(runner.calls, 1)
        self.assertEqual(text, gateway.T["err_generic"])
        self.assertEqual(spoken, text)

    def test_unfinished(self):
        for subtype in ("error_max_turns", "error_max_budget_usd"):
            runner = Runner(([tool_use(HA + "ha_search", "t1"), result(True, subtype)], 1, ""))
            with self.assertLogs("voice_agent_bridge", level="ERROR") as logs:
                text, _, _ = ask(runner)
            self.assertEqual(runner.calls, 1)
            self.assertEqual(text, gateway.T["err_unfinished"])
            self.assertIn(subtype, "\n".join(logs.output))

    def test_partial_answer_kept_no_retry(self):
        events = [text_delta("Je cherche"), result(True, "error_during_execution")]
        runner = Runner((events, 1, ""), (SUCCESS, 0, ""))
        with self.assertLogs("voice_agent_bridge", level="ERROR"):
            text, _, spoken = ask(runner)
        self.assertEqual(runner.calls, 1)
        self.assertEqual(text, "Je cherche " + gateway.T["err_generic"])
        self.assertEqual(spoken, text)

    def test_timeout(self):
        runner = Runner(([], -9, ""), (SUCCESS, 0, ""))
        with self.assertLogs("voice_agent_bridge", level="ERROR") as logs:
            text, _, _ = ask(runner)
        self.assertEqual(runner.calls, 1)
        self.assertEqual(text, gateway.T["err_timeout"])
        self.assertIn("cause: timeout", "\n".join(logs.output))

    def test_errors_and_stderr_logged_auth_not_retried(self):
        events = [result(True, "error_during_execution", errors=["API Error: 401 invalid credentials"])]
        runner = Runner((events, 1, "some stderr line\n"), (SUCCESS, 0, ""))
        with self.assertLogs("voice_agent_bridge", level="ERROR") as logs:
            text, _, _ = ask(runner)
        out = "\n".join(logs.output)
        self.assertIn("API Error: 401 invalid credentials | some stderr line", out)
        self.assertEqual(runner.calls, 1)
        self.assertEqual(text, gateway.T["err_auth"])

    def test_retry_fails_again(self):
        runner = Runner(([result(True, "error_during_execution")], 1, ""),
                        ([result(True, "error_during_execution")], 1, ""))
        with self.assertLogs("voice_agent_bridge", level="ERROR") as logs:
            text, _, _ = ask(runner)
        self.assertEqual(runner.calls, 2)
        self.assertIn("Claude error again", "\n".join(logs.output))
        self.assertEqual(text, gateway.T["err_generic"])

    def test_no_result_event(self):
        runner = Runner(([], 1, ""), ([], 1, ""))
        with self.assertLogs("voice_agent_bridge", level="ERROR") as logs:
            ask(runner)
        self.assertIn("exit code 1; tools called: none; cause: exit code 1", "\n".join(logs.output))

    def test_success_unchanged(self):
        runner = Runner((SUCCESS, 0, ""))
        text, sid, spoken = ask(runner)
        self.assertEqual((text, sid, spoken), ("La TV est allumée.", "s1", "La TV est allumée."))
        self.assertEqual(runner.calls, 1)


class Helpers(unittest.TestCase):
    def test_read_only_tools(self):
        for name in ("ha_search", "ha_get_state", "ha_list_services", "ha_config_get_automation",
                     "ha_eval_template", "ToolSearch", "WebSearch"):
            self.assertTrue(gateway.is_read_only_tool(HA + name) or gateway.is_read_only_tool(name), name)
        for name in ("ha_call_service", "ha_bulk_control", "ha_config_set_automation", "ha_searchx",
                     "ha_restart", "?"):
            self.assertFalse(gateway.is_read_only_tool(HA + name), name)

    def test_redact(self):
        gateway.OPTIONS["claude_token"] = "sk-ant-oat01-SECRETSECRET"
        try:
            text = gateway.one_line("token sk-ant-oat01-SECRETSECRET at http://127.0.0.1:9583/mcp-AbC_d-9 "
                                    "and sk-ant-api03-OTHER", 500)
        finally:
            gateway.OPTIONS["claude_token"] = ""
        self.assertNotIn("SECRET", text)
        self.assertNotIn("AbC_d-9", text)
        self.assertNotIn("OTHER", text)
        self.assertIn("/mcp-***", text)

    def test_messages_exist_in_both_languages(self):
        import prompts
        for lang in ("en", "fr"):
            self.assertTrue(prompts.TEXT[lang]["err_unfinished"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.CRITICAL)
    unittest.main(verbosity=2)
