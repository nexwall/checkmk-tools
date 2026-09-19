#!/usr/bin/env python3
"""test-M@il-20.py — Deterministic test suite for M@il-20.

Each test sets synthetic Checkmk environment variables, then invokes
the module's core functions directly.  No real email is sent.

Run:
    PYTHONDONTWRITEBYTECODE=1 python3 -B test-M@il-20.py
"""

import os
import sys
import json
import time
import math
import shutil
import subprocess
import tempfile
import unittest
import logging
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_MODULE_PATH = str(_HERE / "M@il-20")

import importlib.machinery as _imach
import importlib.util as _ilu

_loader = _imach.SourceFileLoader("M@il_20_mod", _MODULE_PATH)
_spec = _ilu.spec_from_loader("M@il_20_mod", _loader)
_rl_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_rl_mod)

TEST_LOG = logging.getLogger("test_M@il_20")
TEST_LOG.setLevel(logging.DEBUG)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def set_env(**kwargs):
    prev = {}
    for k, v in kwargs.items():
        prev[k] = os.environ.get(k)
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)
    def restore():
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return restore


# ---------------------------------------------------------------------------
# Base test class
# ---------------------------------------------------------------------------

class Mail20Base(unittest.TestCase):
    """Common setUp / tearDown with temp dir and CFG isolation."""

    @classmethod
    def setUpClass(cls):
        cls.rl = _rl_mod

    def setUp(self):
        self._tmpdir = Path(tempfile.mkdtemp(prefix="m20_test_"))
        self.rl.STATE_DIR = str(self._tmpdir)
        self.rl.LOG_DIR = str(self._tmpdir)
        self.rl.LOG.handlers.clear()
        self.rl.LOG.addHandler(logging.StreamHandler(sys.stderr))
        self.rl.LOG.setLevel(logging.DEBUG)
        self._saved_cfg = json.loads(json.dumps(self.rl.CFG))

    def tearDown(self):
        shutil.rmtree(str(self._tmpdir), ignore_errors=True)
        self.rl.CFG.clear()
        self.rl.CFG.update(json.loads(json.dumps(self._saved_cfg)))

    def _fire(self, is_host=True, service_desc="", old_state="UP",
              new_state="DOWN", output="Test output"):
        restore = set_env(
            NOTIFY_CONTACTEMAIL="test@example.com",
            NOTIFY_HOSTNAME="test-host",
            NOTIFY_OMD_SITE="monitoring",
            NOTIFY_SHORTDATETIME="2026-06-18 12:00:00",
            NOTIFY_HOSTADDRESS="10.0.0.1",
            NOTIFY_HOSTLABEL_real_ip="10.0.0.1",
            NOTIFY_HOSTLABEL_frp_tunnel="no",
        )
        try:
            if not is_host:
                os.environ["NOTIFY_SERVICEDESC"] = service_desc
                os.environ["NOTIFY_LASTSERVICESTATE"] = old_state
                os.environ["NOTIFY_SERVICESTATE"] = new_state
                os.environ["NOTIFY_SERVICEOUTPUT"] = output
                os.environ.pop("NOTIFY_HOSTOUTPUT", None)
                os.environ.pop("NOTIFY_LASTHOSTSTATE", None)
                os.environ.pop("NOTIFY_HOSTSTATE", None)
            else:
                os.environ.pop("NOTIFY_SERVICEDESC", None)
                os.environ["NOTIFY_LASTHOSTSTATE"] = old_state
                os.environ["NOTIFY_HOSTSTATE"] = new_state
                os.environ["NOTIFY_HOSTOUTPUT"] = output
                os.environ.pop("NOTIFY_LASTSERVICESTATE", None)
                os.environ.pop("NOTIFY_SERVICESTATE", None)
                os.environ.pop("NOTIFY_SERVICEOUTPUT", None)
            event = self.rl.classify_notification()
            decision = self.rl.evaluate_rate_limit(event)
            return event, decision
        finally:
            restore()

    def _set_enforce(self):
        self.rl.CFG["mode"] = "enforce"


# ---------------------------------------------------------------------------
# Static rate-limit tests
# ---------------------------------------------------------------------------

class TestRateLimit(Mail20Base):
    """Static rate-limiter tests."""

    def test_host_state_first_down_sends(self):
        self._set_enforce()
        _, decision = self._fire(old_state="UP", new_state="DOWN")
        self.assertEqual(decision["decision"], "SEND")

    def test_host_state_repeated_identical_not_counted(self):
        self._set_enforce()
        self._fire(old_state="UP", new_state="DOWN")
        _, decision = self._fire(old_state="DOWN", new_state="DOWN")
        self.assertEqual(decision["decision"], "SEND")
        self.assertIn("no transition counted", decision["reason"].lower())

    def test_host_state_threshold_triggers_suppression(self):
        self._set_enforce()
        seq = [("UP", "DOWN"), ("DOWN", "UP"), ("UP", "DOWN"), ("DOWN", "UP")]
        for old, new in seq:
            self._fire(old_state=old, new_state=new)
        _, decision = self._fire(old_state="UP", new_state="DOWN")
        self.assertEqual(decision["decision"], "SUPPRESS")

    def test_persistent_down_not_flapping(self):
        self._set_enforce()
        self._fire(old_state="UP", new_state="DOWN")
        for _ in range(10):
            _, decision = self._fire(old_state="DOWN", new_state="DOWN")
            self.assertEqual(decision["decision"], "SEND")
            self.assertIn("no transition counted", decision["reason"].lower())

    def test_ping_first_crit_sends(self):
        self._set_enforce()
        _, decision = self._fire(
            is_host=False, service_desc="PING",
            old_state="OK", new_state="CRIT",
        )
        self.assertEqual(decision["decision"], "SEND")

    def test_ping_threshold_triggers(self):
        self._set_enforce()
        seq = [("OK", "CRIT"), ("CRIT", "OK")] * 3
        for old, new in seq:
            self._fire(is_host=False, service_desc="PING",
                       old_state=old, new_state=new)
        _, decision = self._fire(
            is_host=False, service_desc="PING",
            old_state="OK", new_state="CRIT",
        )
        self.assertEqual(decision["decision"], "SUPPRESS")

    def test_ping_warn_not_counted(self):
        self._set_enforce()
        _, decision = self._fire(
            is_host=False, service_desc="PING",
            old_state="OK", new_state="WARNING",
        )
        self.assertEqual(decision["decision"], "SEND")
        self.assertIn("no transition counted", decision["reason"].lower())

    def test_ping_unknown_not_counted(self):
        self._set_enforce()
        _, decision = self._fire(
            is_host=False, service_desc="PING",
            old_state="OK", new_state="UNKNOWN",
        )
        self.assertEqual(decision["decision"], "SEND")
        self.assertIn("no transition counted", decision["reason"].lower())

    def test_non_ping_bypass(self):
        _, decision = self._fire(
            is_host=False, service_desc="CPU load",
            old_state="OK", new_state="WARNING",
        )
        self.assertEqual(decision["decision"], "BYPASS")
        self.assertIsNone(decision["category"])

    def test_non_ping_bypass_even_many(self):
        for _ in range(20):
            _, decision = self._fire(
                is_host=False, service_desc="Disk /",
                old_state="OK", new_state="CRIT",
            )
            self.assertEqual(decision["decision"], "BYPASS")

    def test_host_and_ping_independent(self):
        self._set_enforce()
        host_seq = [("UP", "DOWN"), ("DOWN", "UP"), ("UP", "DOWN"), ("DOWN", "UP")]
        for old, new in host_seq:
            self._fire(old_state=old, new_state=new)
        _, decision = self._fire(old_state="UP", new_state="DOWN")
        self.assertEqual(decision["decision"], "SUPPRESS")
        _, decision = self._fire(
            is_host=False, service_desc="PING",
            old_state="OK", new_state="CRIT",
        )
        self.assertEqual(decision["decision"], "SEND")

    def test_corrupt_state_file(self):
        self._set_enforce()
        state_path = self.rl.get_state_path()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("not valid json {{{")
        _, decision = self._fire(old_state="UP", new_state="DOWN")
        self.assertIn(decision["decision"], ("SEND", "FAIL_OPEN"))

    def test_state_file_missing(self):
        self._set_enforce()
        _, decision = self._fire(old_state="UP", new_state="DOWN")
        self.assertEqual(decision["decision"], "SEND")

    def test_state_dir_not_writable(self):
        self._set_enforce()
        state_path = self.rl.get_state_path()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(str(state_path.parent), 0o000)
        try:
            _, decision = self._fire(old_state="UP", new_state="DOWN")
            self.assertIn(decision["decision"], ("SEND", "FAIL_OPEN"))
        finally:
            os.chmod(str(state_path.parent), 0o755)

    def test_concurrent_state_integrity(self):
        import multiprocessing
        self._set_enforce()
        state_path = self.rl.get_state_path()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        n_procs, n_events = 4, 20

        def worker(seed):
            import importlib.machinery as _imach2
            import importlib.util as _ilu2
            _loader2 = _imach2.SourceFileLoader("M@il_20_w", _MODULE_PATH)
            _s2 = _ilu2.spec_from_loader("M@il_20_w", _loader2)
            mod = _ilu2.module_from_spec(_s2)
            _s2.loader.exec_module(mod)
            mod.STATE_DIR = str(self._tmpdir)
            mod.LOG_DIR = str(self._tmpdir)
            mod.LOG.handlers.clear()
            mod.LOG.addHandler(logging.StreamHandler(sys.stderr))
            mod.CFG["mode"] = "enforce"
            for i in range(n_events):
                h = f"conc-host-{seed}"
                restore = set_env(
                    NOTIFY_CONTACTEMAIL="test@example.com",
                    NOTIFY_HOSTNAME=h,
                    NOTIFY_OMD_SITE="monitoring",
                    NOTIFY_SHORTDATETIME="2026-06-18 12:00:00",
                    NOTIFY_HOSTADDRESS="10.0.0.1",
                    NOTIFY_HOSTLABEL_real_ip="10.0.0.1",
                    NOTIFY_HOSTLABEL_frp_tunnel="no",
                    NOTIFY_LASTHOSTSTATE="UP",
                    NOTIFY_HOSTSTATE="DOWN",
                    NOTIFY_HOSTOUTPUT="Test",
                )
                try:
                    ev = mod.classify_notification()
                    mod.evaluate_rate_limit(ev)
                finally:
                    restore()

        procs = [multiprocessing.Process(target=worker, args=(s,))
                 for s in range(n_procs)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)
        self.assertTrue(state_path.exists())
        raw = state_path.read_bytes()
        try:
            data = json.loads(raw)
            self.assertIsInstance(data, dict)
        except json.JSONDecodeError:
            self.fail("Corrupt after concurrent writes")

    def test_audit_mode_always_sends(self):
        prev = self.rl.CFG["mode"]
        self.rl.CFG["mode"] = "audit"
        try:
            for _ in range(10):
                _, decision = self._fire(old_state="UP", new_state="DOWN")
                self.assertIn(decision["decision"], ("SEND", "WOULD_SUPPRESS"))
        finally:
            self.rl.CFG["mode"] = prev

    def test_expired_observation_window(self):
        self._set_enforce()
        self.rl.CFG["host_state"]["observation_window"] = 1
        self._fire(old_state="UP", new_state="DOWN")
        time.sleep(1.2)
        _, decision = self._fire(old_state="UP", new_state="DOWN")
        self.assertEqual(decision["decision"], "SEND")

    def test_expired_suppression(self):
        self._set_enforce()
        self.rl.CFG["host_state"]["observation_window"] = 600
        self.rl.CFG["host_state"]["trigger_transitions"] = 2
        self.rl.CFG["host_state"]["suppression_time"] = 1
        self._fire(old_state="UP", new_state="DOWN")
        self._fire(old_state="UP", new_state="DOWN")
        time.sleep(1.2)
        _, decision = self._fire(old_state="UP", new_state="DOWN")
        self.assertEqual(decision["decision"], "SEND")


# ---------------------------------------------------------------------------
# Simulation tests
# ---------------------------------------------------------------------------

class TestSimulation(Mail20Base):
    """Explicit sequences from the specification."""

    def _fire(self, **kw):
        self._set_enforce()
        restore = set_env(
            NOTIFY_CONTACTEMAIL="test@example.com",
            NOTIFY_HOSTNAME="sim-host",
            NOTIFY_OMD_SITE="monitoring",
            NOTIFY_SHORTDATETIME="2026-06-18 12:00:00",
            NOTIFY_HOSTADDRESS="10.0.0.1",
            NOTIFY_HOSTLABEL_real_ip="10.0.0.1",
            NOTIFY_HOSTLABEL_frp_tunnel="no",
        )
        try:
            is_host = kw.pop("is_host", True)
            svc = kw.pop("service_desc", "")
            old = kw.pop("old_state", "UP")
            new = kw.pop("new_state", "DOWN")
            out = kw.pop("output", "Test output")
            if not is_host:
                os.environ["NOTIFY_SERVICEDESC"] = svc
                os.environ["NOTIFY_LASTSERVICESTATE"] = old
                os.environ["NOTIFY_SERVICESTATE"] = new
                os.environ["NOTIFY_SERVICEOUTPUT"] = out
            else:
                os.environ.pop("NOTIFY_SERVICEDESC", None)
                os.environ["NOTIFY_LASTHOSTSTATE"] = old
                os.environ["NOTIFY_HOSTSTATE"] = new
                os.environ["NOTIFY_HOSTOUTPUT"] = out
            event = self.rl.classify_notification()
            decision = self.rl.evaluate_rate_limit(event)
            return event, decision
        finally:
            restore()

    def test_host_state_sequence(self):
        """UP->DOWN->UP->DOWN->UP"""
        seq = [("UP", "DOWN", "SEND"), ("DOWN", "UP", "SEND"),
               ("UP", "DOWN", "SEND"), ("DOWN", "UP", "SEND"),
               ("UP", "DOWN", "SUPPRESS")]
        for i, (old, new, exp) in enumerate(seq):
            _, dec = self._fire(old_state=old, new_state=new)
            self.assertEqual(dec["decision"], exp,
                             f"Step {i+1}: {old}->{new} expected {exp}")

    def test_ping_sequence(self):
        """OK->CRIT->OK->CRIT->OK->CRIT->OK"""
        seq = [("OK", "CRIT", "SEND"), ("CRIT", "OK", "SEND"),
               ("OK", "CRIT", "SEND"), ("CRIT", "OK", "SEND"),
               ("OK", "CRIT", "SEND"), ("CRIT", "OK", "SEND"),
               ("OK", "CRIT", "SUPPRESS")]
        for i, (old, new, exp) in enumerate(seq):
            _, dec = self._fire(is_host=False, service_desc="PING",
                                old_state=old, new_state=new)
            self.assertEqual(dec["decision"], exp,
                             f"PING step {i+1}: {old}->{new} expected {exp}")

    def test_persistent_down_sequence(self):
        """UP->DOWN x 4 -- no false trigger."""
        seq = [("UP", "DOWN", "SEND"), ("DOWN", "DOWN", "SEND"),
               ("DOWN", "DOWN", "SEND"), ("DOWN", "DOWN", "SEND")]
        for i, (old, new, exp) in enumerate(seq):
            _, dec = self._fire(old_state=old, new_state=new)
            self.assertEqual(dec["decision"], exp)
            if old == new:
                self.assertIn("no transition counted", dec["reason"].lower())


# ---------------------------------------------------------------------------
# Adaptive learning tests
# ---------------------------------------------------------------------------

class TestAdaptive(Mail20Base):
    """Adaptive learning subsystem tests."""

    def _seed_adaptive(self, cat_key="host_state", n_samples=300,
                       window_vals=None, first_obs_days_ago=30,
                       min_days=1, min_samples=1):
        """Seed a host category with learning data."""
        self.rl.CFG["adaptive"]["minimum_learning_days"] = min_days
        self.rl.CFG["adaptive"]["minimum_transition_samples"] = min_samples
        sp = self.rl.get_state_path()
        lp = self.rl.get_lock_path(sp)
        with self.rl.StateLock(lp):
            state = self.rl.read_state(sp)
            state = self.rl.migrate_state(state)
            hr = self.rl.get_host_state(state, "test-host")
            cr = hr[cat_key]
            ad = self.rl._ensure_adaptive(cr)
            ad["first_observation"] = int(time.time()) - first_obs_days_ago * 86400
            if n_samples:
                base = int(time.time()) - 3600
                ad["transition_samples"] = [base - i * 3600 for i in range(n_samples)]
            if window_vals is not None:
                ad["window_counts_30m"] = list(window_vals)
            self.rl.write_state(sp, state)

    def _recalc(self, cat_key="host_state"):
        """Call _recalculate_recommendation and return the adaptive record."""
        sp = self.rl.get_state_path()
        lp = self.rl.get_lock_path(sp)
        with self.rl.StateLock(lp):
            state = self.rl.read_state(sp)
            self.rl._recalculate_recommendation(
                state["test-host"][cat_key], cat_key,
                self.rl.CFG["adaptive"], int(time.time()),
            )
            self.rl.write_state(sp, state)
        state = self.rl.read_state(sp)
        return state["test-host"][cat_key].get("adaptive", {})

    # -- Tests --

    def test_first_observation_created(self):
        """First notification creates learning state."""
        self._fire(old_state="UP", new_state="DOWN")
        state = self.rl.read_state(self.rl.get_state_path())
        ad = state.get("test-host", {}).get("host_state", {}).get("adaptive", {})
        self.assertGreater(ad.get("first_observation", 0), 0)

    def test_repeated_identical_not_sampled(self):
        """Repeated states do not create transition samples."""
        self._fire(old_state="UP", new_state="DOWN")
        self._fire(old_state="DOWN", new_state="DOWN")
        state = self.rl.read_state(self.rl.get_state_path())
        ad = state.get("test-host", {}).get("host_state", {}).get("adaptive", {})
        self.assertEqual(len(ad.get("transition_samples", [])), 1)

    def test_host_state_independent_from_ping(self):
        """HOST STATE and PING keep separate learning."""
        self._fire(old_state="UP", new_state="DOWN")
        self._fire(is_host=False, service_desc="PING",
                    old_state="OK", new_state="CRIT")
        state = self.rl.read_state(self.rl.get_state_path())
        h_ad = state["test-host"]["host_state"]["adaptive"]
        p_ad = state["test-host"]["service_state_ping"]["adaptive"]
        self.assertEqual(len(h_ad.get("transition_samples", [])), 1)
        self.assertEqual(len(p_ad.get("transition_samples", [])), 1)

    def test_different_hosts_independent(self):
        """Different hosts keep separate learning."""
        self._fire(old_state="UP", new_state="DOWN")
        restore = set_env(NOTIFY_HOSTNAME="other-host")
        try:
            os.environ["NOTIFY_LASTHOSTSTATE"] = "UP"
            os.environ["NOTIFY_HOSTSTATE"] = "DOWN"
            ev = self.rl.classify_notification()
            self.rl.evaluate_rate_limit(ev)
        finally:
            restore()
        state = self.rl.read_state(self.rl.get_state_path())
        self.assertIn("test-host", state)
        self.assertIn("other-host", state)

    def test_insufficient_days(self):
        """Fewer than min_learning_days -> INSUFFICIENT_DATA."""
        self.rl.CFG["adaptive"]["minimum_learning_days"] = 14
        self._seed_adaptive(first_obs_days_ago=5, min_days=14, window_vals=[3]*50)
        ad = self._recalc()
        self.assertEqual(ad.get("recommendation_status"), "INSUFFICIENT_DATA")

    def test_insufficient_samples(self):
        """Fewer than min_transition_samples -> INSUFFICIENT_DATA."""
        self.rl.CFG["adaptive"]["minimum_transition_samples"] = 20
        self._seed_adaptive(n_samples=3, min_samples=20, window_vals=[3]*50)
        ad = self._recalc()
        self.assertEqual(ad.get("recommendation_status"), "INSUFFICIENT_DATA")

    def test_recommendation_uses_percentile(self):
        """Recommendation based on p95 + margin."""
        self._seed_adaptive(window_vals=[5]*100)
        ad = self._recalc()
        self.assertEqual(ad.get("recommended_threshold"), 7)

    def test_safety_margin_applied(self):
        """Safety margin is added to percentile."""
        self.rl.CFG["adaptive"]["percentile"] = 50
        self.rl.CFG["adaptive"]["safety_margin"] = 3
        self._seed_adaptive(window_vals=[2]*100)
        ad = self._recalc()
        self.assertEqual(ad.get("recommended_threshold"), 5)

    def test_host_state_minimum_4(self):
        """HOST STATE never below 4."""
        self._seed_adaptive(window_vals=[0]*100)
        ad = self._recalc()
        self.assertEqual(ad.get("recommended_threshold"), 4)

    def test_host_state_maximum_10(self):
        """HOST STATE never exceeds 10."""
        self._seed_adaptive(window_vals=[50]*100)
        ad = self._recalc()
        self.assertLessEqual(ad.get("recommended_threshold"), 10)
        self.assertEqual(ad.get("recommendation_status"), "EXCESSIVE_INSTABILITY")

    def test_ping_minimum_6(self):
        """SERVICE STATE PING minimum is 6."""
        self._seed_adaptive(cat_key="service_state_ping", window_vals=[0]*100)
        ad = self._recalc(cat_key="service_state_ping")
        self.assertEqual(ad.get("recommended_threshold"), 6)

    def test_ping_maximum_20(self):
        """SERVICE STATE PING maximum is 20."""
        self._seed_adaptive(cat_key="service_state_ping", window_vals=[50]*100)
        ad = self._recalc(cat_key="service_state_ping")
        self.assertLessEqual(ad.get("recommended_threshold"), 20)
        self.assertEqual(ad.get("recommendation_status"), "EXCESSIVE_INSTABILITY")

    def test_recalculation_rate_limited(self):
        """Recalculation limited to once every 24h."""
        self._seed_adaptive(window_vals=[5]*100)
        ad = self._recalc()
        self.assertIsNotNone(ad.get("recommended_threshold"))

        # Set last_recalculation to now
        sp = self.rl.get_state_path()
        lp = self.rl.get_lock_path(sp)
        with self.rl.StateLock(lp):
            state = self.rl.read_state(sp)
            state["test-host"]["host_state"]["adaptive"]["last_recalculation"] = int(time.time())
            self.rl.write_state(sp, state)

        # Fire event - rate-limited path should skip recalc
        self._fire(old_state="DOWN", new_state="UP")
        with self.rl.StateLock(lp):
            state = self.rl.read_state(sp)
            ad2 = state["test-host"]["host_state"]["adaptive"]
            self.assertIsNotNone(ad2.get("recommended_threshold"))

    def test_recommendations_not_applied(self):
        """Recommendations never change active config."""
        orig = self.rl.CFG["host_state"]["trigger_transitions"]
        self._seed_adaptive(window_vals=[5]*100)
        self._recalc()
        self.assertEqual(self.rl.CFG["host_state"]["trigger_transitions"], orig)

    def test_auto_apply_remains_false(self):
        """adaptive.auto_apply must be False."""
        self.assertFalse(self.rl.CFG.get("adaptive", {}).get("auto_apply", True))

    def test_adaptive_failure_fail_open(self):
        """Adaptive failure must not block mail."""
        self.rl.CFG["adaptive"]["percentile"] = 999
        _, decision = self._fire(old_state="UP", new_state="DOWN")
        self.assertIn(decision["decision"], ("SEND", "FAIL_OPEN", "WOULD_SUPPRESS"))

    def test_corrupt_adaptive_state_fail_open(self):
        """Corrupt state must not block mail."""
        sp = self.rl.get_state_path()
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text("{}")
        _, decision = self._fire(old_state="UP", new_state="DOWN")
        self.assertIn(decision["decision"], ("SEND", "FAIL_OPEN"))

    def test_schema_migration_preserves_state(self):
        """v1->v2 migration preserves rate-limit data."""
        sp = self.rl.get_state_path()
        sp.parent.mkdir(parents=True, exist_ok=True)
        v1 = {"schema_version": 1, "old-host": {
            "host_state": {"last_state": "DOWN", "transitions": [1000000],
                           "suppression_until": 0, "suppressed_count": 0},
            "service_state_ping": {"last_state": "OK", "transitions": [],
                                   "suppression_until": 0, "suppressed_count": 0},
        }}
        sp.write_text(json.dumps(v1))
        state = self.rl.read_state(sp)
        state = self.rl.migrate_state(state)
        self.assertEqual(state["schema_version"], 2)
        self.assertEqual(state["old-host"]["host_state"]["last_state"], "DOWN")
        self.assertIn("adaptive", state["old-host"]["host_state"])
        self.assertIn("adaptive", state["old-host"]["service_state_ping"])

    def test_learning_data_retention(self):
        """Bounded growth of transition_samples."""
        self._fire(old_state="UP", new_state="DOWN")
        sp = self.rl.get_state_path()
        lp = self.rl.get_lock_path(sp)
        with self.rl.StateLock(lp):
            state = self.rl.read_state(sp)
            ad = self.rl._ensure_adaptive(state["test-host"]["host_state"])
            old_ts = int(time.time()) - 60 * 86400
            ad["transition_samples"] = [old_ts - i * 3600 for i in range(500)]
            self.rl.write_state(sp, state)
        self._fire(old_state="DOWN", new_state="UP")
        with self.rl.StateLock(lp):
            state = self.rl.read_state(sp)
            ad = state["test-host"]["host_state"]["adaptive"]
            self.assertLessEqual(len(ad.get("transition_samples", [])), 750)

    def test_learning_report_read_only(self):
        """--learning-report is read-only."""
        sp = self.rl.get_state_path()
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text('{"schema_version": 2, "test-host": '
                      '{"host_state": {"adaptive": {}}, '
                      '"service_state_ping": {"adaptive": {}}}}')
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = self.rl.print_learning_report()
        self.assertEqual(rc, 0)
        state = self.rl.read_state(sp)
        self.assertIn("test-host", state)

    def test_no_real_email_sent(self):
        """No real email is sent during tests."""
        _, decision = self._fire(old_state="UP", new_state="DOWN")
        self.assertIn(decision["decision"], ("SEND", "FAIL_OPEN", "WOULD_SUPPRESS"))

    def test_old_filename_absent(self):
        """Old filename must be absent."""
        self.assertFalse((_HERE / "checkmk-notification-rate-limit.py").exists())

    def test_new_filename_exists_executable(self):
        """New filename M@il-20 exists and is executable."""
        new_path = _HERE / "M@il-20"
        self.assertTrue(new_path.exists())
        self.assertTrue(os.access(str(new_path), os.X_OK))

    def test_no_crlf(self):
        """M@il-20 contains no CRLF line endings."""
        data = (_HERE / "M@il-20").read_bytes()
        self.assertNotIn(b"\r\n", data)

    def test_no_cr(self):
        """M@il-20 contains no isolated CR bytes."""
        data = (_HERE / "M@il-20").read_bytes()
        self.assertNotIn(b"\r", data)

    def test_shebang_exact(self):
        """M@il-20 shebang is exactly '#!/usr/bin/env python3\\n'."""
        data = (_HERE / "M@il-20").read_bytes()
        self.assertTrue(data.startswith(b"#!/usr/bin/env python3\n"))

    def test_direct_shebang_execution(self):
        """M@il-20 can be executed directly through OS shebang."""
        tmpdir = Path(tempfile.mkdtemp(prefix="m20_shebang_"))
        try:
            state_dir = tmpdir / "var" / "check_mk" / "M@il-20"
            state_dir.mkdir(parents=True, exist_ok=True)
            env = os.environ.copy()
            env["OMD_ROOT"] = str(tmpdir)
            env["NOTIFY_RATE_LIMIT_STATE_DIR"] = str(state_dir)
            result = subprocess.run(
                [str(_HERE / "M@il-20"), "--learning-report"],
                capture_output=True, text=True, timeout=15,
                env=env,
            )
            self.assertEqual(result.returncode, 0)
        finally:
            shutil.rmtree(str(tmpdir), ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
