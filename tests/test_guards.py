"""Unit tests for the classifiers. Run: python3 -m unittest discover -s tests"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "guards"))
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()

import guardlib as g  # noqa: E402
import reboot_reason_guard as r  # noqa: E402
import thermal_guard as t  # noqa: E402


def facts(action=None, resumed=False, thermal=(), severe=(), key_long=False):
    return {"action": action, "resumed_after_action": resumed, "power_key_long": key_long,
            "thermal": list(thermal), "severe": list(severe), "last_entry": 0}


class BootEndTests(unittest.TestCase):
    def cat(self, bits=(), f=None, hb=None, dumps=()):
        return r.classify_boot_end(set(bits), f or facts(), hb, list(dumps))[0]

    def test_normal(self):
        self.assertEqual(self.cat({19}, facts("reboot")), "normal_reboot")
        self.assertEqual(self.cat({19}, facts("power off")), "normal_power_off")

    def test_thermal_trip_beats_everything(self):
        self.assertEqual(self.cat({0}, facts("reboot")), "thermal_shutdown_hw")
        self.assertEqual(self.cat({9}), "thermal_shutdown_hw")

    def test_kernel_thermal(self):
        f = facts("power off", thermal=["thermal thermal_zone0: critical temperature reached, shutting down"])
        self.assertEqual(self.cat({19}, f), "thermal_shutdown_kernel")

    def test_panic(self):
        self.assertEqual(self.cat({19}, dumps=["/home/.steamos/offload/var/kdumpst/logs/x.zip"]), "kernel_panic")
        self.assertEqual(self.cat(f=facts(severe=["kernel_panic: Kernel panic - not syncing"])), "kernel_panic")
        # minidumps are not panics
        self.assertEqual(self.cat({19}, dumps=["/var/lib/steamos-log-submitter/pending/minidump/1-mangoapp.dmp"]),
                         "unclean_shutdown")

    def test_watchdog_and_hw_fault(self):
        self.assertEqual(self.cat({25}), "watchdog_reset")
        self.assertEqual(self.cat({27}), "hardware_fault")

    def test_forced_off(self):
        self.assertEqual(self.cat({1}), "forced_power_off")

    def test_battery_and_suspend(self):
        low = {"battery": 1, "ac": False, "cpu_c": 40, "gpu_c": 40}
        self.assertEqual(self.cat(hb=low), "battery_depleted")
        self.assertEqual(self.cat(f=facts("suspend"), hb=low), "died_in_suspend")
        self.assertEqual(self.cat(f=facts("suspend", resumed=True), hb=low), "battery_depleted")

    def test_hot_heartbeat(self):
        self.assertEqual(self.cat(hb={"battery": 80, "ac": True, "cpu_c": 99, "gpu_c": 80}), "suspected_thermal")

    def test_unclean(self):
        self.assertEqual(self.cat({19}), "unclean_shutdown")


class EventTests(unittest.TestCase):
    def kind(self, msg):
        ev = r.classify_event(msg)
        return ev[0] if ev else None

    def test_gpu(self):
        self.assertEqual(self.kind("amdgpu 0000:c2:00.0: amdgpu: ring gfx_0.0.0 timeout, signaled seq=1, emitted seq=3"), "gpu_hang")
        self.assertEqual(self.kind("amdgpu 0000:c2:00.0: amdgpu: GPU reset begin!"), "gpu_hang")
        self.assertEqual(self.kind("amdgpu 0000:c2:00.0: amdgpu: [gfxhub] page fault (src_id:0 ring:24 vmid:3 pasid:32771)"), "gpu_fault")

    def test_boot_chatter_ignored(self):
        self.assertIsNone(self.kind("amdgpu 0000:c2:00.0: amdgpu: ring gfx_0.0.0 uses VM inv eng 0 on hub 0"))
        self.assertIsNone(self.kind("Kernel command line: BOOT_IMAGE=/boot/vmlinuz amdgpu.lockup_timeout=5000"))
        self.assertFalse(t.is_thermal_message("ACPI: thermal: Thermal Zone [TZ01] (79 C)"))
        self.assertFalse(t.is_thermal_message("thermal_sys: Registered thermal governor 'step_wise'"))

    def test_kernel_and_memory(self):
        self.assertEqual(self.kind("Kernel panic - not syncing: Fatal exception"), "kernel_panic")
        self.assertEqual(self.kind("watchdog: BUG: soft lockup - CPU#3 stuck for 22s!"), "lockup")
        self.assertEqual(self.kind("mce: [Hardware Error]: Machine check events logged"), "machine_check")
        self.assertEqual(self.kind("Out of memory: Killed process 4242 (GameThread)"), "oom_kill")
        self.assertEqual(self.kind("Process 1234 (Game.exe) of user 1000 dumped core."), "process_crash")

    def test_own_records_skipped(self):
        self.assertTrue(r.is_own_record({"_SYSTEMD_USER_UNIT": "reboot-reason-guard.service"}))
        self.assertTrue(r.is_own_record({"_SYSTEMD_USER_UNIT": "thermal-guard.service"}))
        self.assertFalse(r.is_own_record({"_SYSTEMD_UNIT": "gamescope-session.service", "_PID": "1"}))

    def test_thermal_messages(self):
        self.assertTrue(t.is_thermal_message("thermal thermal_zone0: critical temperature reached, shutting down"))


class ThermalMonitorTests(unittest.TestCase):
    def setUp(self):
        cfg = g._merge(g.DEFAULTS, {})
        self.log, self.notify = mock.Mock(), mock.Mock()
        self.mon = t.ThermalMonitor(cfg, self.log, self.notify)
        self.snap = mock.patch.object(g, "snapshot", return_value={}).start()
        self.addCleanup(mock.patch.stopall)

    def run_temps(self, temps, step=5):
        for i, c in enumerate(temps):
            self.mon.step(i * step, {"cpu_c": c, "gpu_c": 40})

    def kinds(self):
        return [c.args[0] for c in self.log.write.call_args_list]

    def test_short_spike_ignored(self):
        self.run_temps([80, 92, 80, 80])
        self.assertEqual(self.kinds(), [])

    def test_sustained_warning_then_end(self):
        self.run_temps([91, 91, 91, 91, 84, 80])
        self.assertEqual(self.kinds(), ["hot_warning", "hot_episode_end"])
        self.assertFalse(self.notify.send.call_args.kwargs["critical"])

    def test_critical_needs_two_samples(self):
        self.run_temps([98, 80])
        self.assertEqual(self.kinds(), [])
        self.run_temps([98, 98])
        self.assertIn("hot_critical", self.kinds())
        self.assertTrue(self.notify.send.call_args.kwargs["critical"])


if __name__ == "__main__":
    unittest.main()
