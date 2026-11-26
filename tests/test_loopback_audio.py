import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loopback_audio import _find_pyaudio_monitor_index, _open_pyaudio_monitor_stream


class TestLoopbackAudioDeviceSelection(unittest.TestCase):
    def setUp(self):
        self.pyaudio = MagicMock()
        self.devices = [
            {"name": "default", "maxInputChannels": 32, "hostApi": 0},
            {"name": "pulse", "maxInputChannels": 32, "hostApi": 0},
        ]
        self.pyaudio.get_device_count.return_value = len(self.devices)
        self.pyaudio.get_device_info_by_index.side_effect = lambda index: self.devices[index]
        self.pyaudio.get_host_api_info_by_index.return_value = {"name": "ALSA"}

    def test_selects_alsa_pulse_endpoint_for_named_monitor(self):
        index = _find_pyaudio_monitor_index(
            self.pyaudio,
            "alsa_output.test.monitor",
        )

        self.assertEqual(index, 1)

    def test_does_not_fall_back_to_default_input_without_monitor_name(self):
        index = _find_pyaudio_monitor_index(self.pyaudio, None)

        self.assertIsNone(index)

    def test_does_not_select_pulse_device_from_another_host_api(self):
        self.pyaudio.get_host_api_info_by_index.return_value = {"name": "Other"}

        index = _find_pyaudio_monitor_index(
            self.pyaudio,
            "alsa_output.test.monitor",
        )

        self.assertIsNone(index)


class TestPulseSourceSelection(unittest.TestCase):
    def test_sets_monitor_source_only_while_opening_stream(self):
        audio = MagicMock()
        audio.open.side_effect = lambda **kwargs: os.environ["PULSE_SOURCE"]

        for previous_source in (None, "previous-source"):
            with self.subTest(previous_source=previous_source), patch.dict(os.environ):
                if previous_source is None:
                    os.environ.pop("PULSE_SOURCE", None)
                else:
                    os.environ["PULSE_SOURCE"] = previous_source

                stream = _open_pyaudio_monitor_stream(
                    audio,
                    audio_format=8,
                    device_index=1,
                    monitor_source_name="alsa_output.test.monitor",
                    channels=2,
                    rate=44100,
                    chunk_size=1024,
                )

                self.assertEqual(stream, "alsa_output.test.monitor")
                self.assertEqual(os.environ.get("PULSE_SOURCE"), previous_source)

        self.assertEqual(audio.open.call_count, 2)
        audio.open.assert_called_with(
            format=8,
            channels=2,
            rate=44100,
            input=True,
            input_device_index=1,
            frames_per_buffer=1024,
        )


if __name__ == "__main__":
    unittest.main()
