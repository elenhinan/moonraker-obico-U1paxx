import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import mock_open, patch

from moonraker_obico import janus_config_builder, utils
from moonraker_obico.config import Config
from moonraker_obico.webcam_stream import JANUS_ADMIN_WS_PORT, WebcamStreamer


RTSP_CONFIG = '''\
[server]
url = https://example.test

[moonraker]
host = 127.0.0.1
port = 7125

[webcam]
snapshot_url = http://127.0.0.1/webcam/snapshot.jpg
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

    def test_h264_rtsp_uses_ffmpeg_rtp_repacketizer_and_allocates_ports(self):
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
        self.assertEqual(JANUS_ADMIN_WS_PORT + 1, webcam.runtime['videoport'])
        self.assertEqual(JANUS_ADMIN_WS_PORT + 2, webcam.runtime['videortcpport'])
        self.assertEqual(JANUS_ADMIN_WS_PORT + 3, webcam.runtime['dataport'])

        with patch.object(janus_config_builder, 'RUNTIME_JANUS_ETC_DIR', temp_dir):
            janus_config_builder.build_janus_plugin_streaming_jcfg(streamer.webcams)

        jcfg_path = os.path.join(temp_dir, 'janus.plugin.streaming.jcfg')
        with open(jcfg_path) as f:
            contents = f.read()

        self.assertIn('type = "rtp"', contents)
        self.assertIn('id = 1', contents)
        self.assertIn(f'videoport =  {JANUS_ADMIN_WS_PORT + 1}', contents)
        self.assertIn(f'videortcpport = {JANUS_ADMIN_WS_PORT + 2}', contents)
        self.assertIn(f'dataport = {JANUS_ADMIN_WS_PORT + 3}', contents)

        with patch.object(streamer, 'start_ffmpeg') as mock_start_ffmpeg:
            streamer.h264_rtsp(webcam)
            mock_start_ffmpeg.assert_called_once_with(
                JANUS_ADMIN_WS_PORT + 1,
                '-rtsp_transport tcp -fflags nobuffer -flags low_delay -i rtsp://127.0.0.1:8554/stream -c:v copy',
                retry_after_quit=True,
                pkt_size=1200,
            )

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

    def test_board_id_detects_snapmaker_u1(self):
        fake_files = {
            '/sys/firmware/devicetree/base/model': 'Rockchip RK3562 EVB2 DDR4 V10 Board\x00',
            '/etc/os-release': 'ID=buildroot\nVERSION_ID=2024.02\nRK_BUILD_INFO="snapmaker@build-srv - rockchip_rk3562_snapmaker_lava"\n',
        }

        def fake_isfile(path):
            return path in fake_files

        def fake_open(path, *args, **kwargs):
            return mock_open(read_data=fake_files[path])()

        with patch('moonraker_obico.utils.os.path.isfile', side_effect=fake_isfile), \
                patch('builtins.open', side_effect=fake_open):
            self.assertEqual('u1', utils.board_id())

    def test_board_id_ignores_non_snapmaker_rk3562(self):
        fake_files = {
            '/sys/firmware/devicetree/base/model': 'Rockchip RK3562 EVB2 DDR4 V10 Board\x00',
            '/etc/os-release': 'ID=debian\nVERSION_ID=12\n',
        }

        def fake_isfile(path):
            return path in fake_files

        def fake_open(path, *args, **kwargs):
            return mock_open(read_data=fake_files[path])()

        with patch('moonraker_obico.utils.os.path.isfile', side_effect=fake_isfile), \
                patch('builtins.open', side_effect=fake_open):
            self.assertEqual('NA', utils.board_id())

    def test_find_precompiled_dir_resolves_u1_variant(self):
        with patch.object(janus_config_builder, 'board_id', return_value='u1'), \
                patch.object(janus_config_builder, 'distro_id', 'buildroot'), \
                patch.object(janus_config_builder.distro, 'major_version', return_value='2024'), \
                patch.object(janus_config_builder, 'os_bit', return_value='64-bit'):
            precompiled_dir, requested, chosen = janus_config_builder.find_precompiled_dir()

        self.assertEqual('u1.buildroot.2024.64-bit', requested)
        self.assertEqual('u1.buildroot.2024.64-bit', chosen)
        self.assertTrue(os.path.isfile(os.path.join(precompiled_dir, 'bin', 'janus')))
        self.assertTrue(os.path.isfile(os.path.join(precompiled_dir, 'lib', 'libgnutls.so.30')))
        self.assertTrue(os.path.isfile(os.path.join(precompiled_dir, 'lib', 'libogg.so.0')))

    def test_find_precompiled_dir_u1_falls_back_for_newer_buildroot(self):
        with patch.object(janus_config_builder, 'board_id', return_value='u1'), \
                patch.object(janus_config_builder, 'distro_id', 'buildroot'), \
                patch.object(janus_config_builder.distro, 'major_version', return_value='2026'), \
                patch.object(janus_config_builder, 'os_bit', return_value='64-bit'):
            precompiled_dir, requested, chosen = janus_config_builder.find_precompiled_dir()

        self.assertEqual('u1.buildroot.2026.64-bit', requested)
        self.assertEqual('u1.buildroot.2024.64-bit', chosen)
        self.assertTrue(os.path.isdir(precompiled_dir))

    def test_build_janus_jcfg_sets_min_nack_queue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(janus_config_builder, 'RUNTIME_JANUS_ETC_DIR', temp_dir), \
                    patch.object(janus_config_builder, 'find_system_janus_paths', return_value=('/usr/bin/janus', '/usr/lib')):
                janus_config_builder.build_janus_jcfg('test-token')

            with open(os.path.join(temp_dir, 'janus.jcfg')) as f:
                contents = f.read()

            self.assertIn('min_nack_queue = 500', contents)


if __name__ == '__main__':
    unittest.main()
