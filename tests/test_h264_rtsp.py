import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from moonraker_obico import janus_config_builder
from moonraker_obico.config import Config
from moonraker_obico.webcam_stream import JANUS_ADMIN_WS_PORT, WebcamStreamer


RTSP_CONFIG = '''\
[server]
url = https://example.test

[moonraker]
host = 127.0.0.1
port = 7125

[webcam]
snapshot_url = http://127.0.0.1:8080/webcam/snapshot.jpg
stream_url = rtsp://127.0.0.1:8554/stream
stream_mode = h264_rtsp
disable_video_streaming = False

[logging]
level = INFO

[tunnel]
'''


class H264RtspTests(unittest.TestCase):

    def _load_config(self, cfg_text):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        config_path = os.path.join(temp_dir.name, 'moonraker-obico.cfg')
        with open(config_path, 'w') as f:
            f.write(cfg_text)
        config = Config(config_path)
        config.load_from_config_file()
        return config, temp_dir.name

    def test_h264_rtsp_uses_config_stream_url_and_allocates_dataport(self):
        config, temp_dir = self._load_config(RTSP_CONFIG)
        app_model = SimpleNamespace(
            printer_state=None,
            config=config,
            linked_printer={'is_pro': True},
        )
        streamer = WebcamStreamer(None, None, None, app_model, None)
        streamer.webcams = config.webcams

        with patch('moonraker_obico.webcam_stream.find_ffmpeg_h264_encoder') as mock_find_encoder:
            streamer.find_streaming_params()
            mock_find_encoder.assert_not_called()

        streamer.assign_janus_params()

        webcam = streamer.webcams[0]
        self.assertEqual('h264_rtsp', webcam.streaming_params['mode'])
        self.assertEqual(1, webcam.runtime['stream_id'])
        self.assertEqual(JANUS_ADMIN_WS_PORT + 1, webcam.runtime['dataport'])

        with patch.object(janus_config_builder, 'RUNTIME_JANUS_ETC_DIR', temp_dir):
            janus_config_builder.build_janus_plugin_streaming_jcfg(streamer.webcams)

        jcfg_path = os.path.join(temp_dir, 'janus.plugin.streaming.jcfg')
        with open(jcfg_path) as f:
            contents = f.read()

        self.assertIn('type = "rtsp"', contents)
        self.assertIn('id = 1', contents)
        self.assertIn('url = "rtsp://127.0.0.1:8554/stream"', contents)
        self.assertIn(f'dataport = {JANUS_ADMIN_WS_PORT + 1}', contents)

    def test_h264_rtsp_missing_stream_url_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            webcam = SimpleNamespace(
                stream_url='',
                streaming_params={'mode': 'h264_rtsp'},
                runtime={'stream_id': 1, 'dataport': 17732},
            )
            with patch.object(janus_config_builder, 'RUNTIME_JANUS_ETC_DIR', temp_dir):
                with self.assertRaisesRegex(Exception, 'stream_url is required'):
                    janus_config_builder.build_janus_plugin_streaming_jcfg([webcam])

    def test_h264_rtsp_falls_back_to_rtsp_port(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            webcam = SimpleNamespace(
                stream_url='',
                streaming_params={'mode': 'h264_rtsp', 'rtsp_port': 8554},
                runtime={'stream_id': 1, 'dataport': 17732},
            )
            with patch.object(janus_config_builder, 'RUNTIME_JANUS_ETC_DIR', temp_dir):
                janus_config_builder.build_janus_plugin_streaming_jcfg([webcam])

            jcfg_path = os.path.join(temp_dir, 'janus.plugin.streaming.jcfg')
            with open(jcfg_path) as f:
                contents = f.read()

            self.assertIn('url = "rtsp://127.0.0.1:8554/stream.h264"', contents)


if __name__ == '__main__':
    unittest.main()
