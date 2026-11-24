"""Cloud adapter contract tests; all network access is mocked."""
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py'))
import plate_api


class PlateApiTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict('os.environ', {'PLATE_API_TOKEN': 'test-only', 'PLATE_API_MODE': 'fallback'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        plate_api._retry_after = 0
        plate_api._last_attempt = float('-inf')

    def test_multipart_auth_regions_and_coordinate_scaling(self):
        payload = dict(results=[dict(plate='51f12345', score=0.96,
                                    box=dict(xmin=10, ymin=20, xmax=110, ymax=60))])
        with patch.object(plate_api, '_encode_image', return_value=(b'jpeg', 0.5)), \
                patch.object(plate_api.urllib.request, 'urlopen', return_value=BytesIO(json.dumps(payload).encode())) as http:
            result = plate_api.recognize('synthetic.jpg')
        self.assertEqual(result, ('51F12345', (20, 40, 200, 80), 0.96))
        req = http.call_args.args[0]
        self.assertEqual(req.get_header('Authorization'), 'Token test-only')
        self.assertIn(b'name="regions"\r\n\r\nvn', req.data)
        self.assertEqual(http.call_args.kwargs['timeout'], 5)

    def test_quota_error_cools_down_instead_of_retrying_every_camera_frame(self):
        error = urllib.error.HTTPError(plate_api.DEFAULT_URL, 429, 'quota', {}, None)
        with patch.object(plate_api, '_encode_image', return_value=(b'jpeg', 1)) as encode, \
                patch.object(plate_api.urllib.request, 'urlopen', side_effect=error) as http:
            with self.assertRaises(RuntimeError):
                plate_api.recognize('synthetic.jpg')
            with self.assertRaises(plate_api.ApiUnavailable):
                plate_api.recognize('synthetic.jpg')
        self.assertEqual(http.call_count, 1)
        self.assertEqual(encode.call_count, 1)

    def test_live_cloud_interval_limits_requests(self):
        with patch.object(plate_api, '_encode_image', return_value=(b'jpeg', 1)), \
                patch.object(plate_api.urllib.request, 'urlopen', return_value=BytesIO(b'{"results": []}')) as http:
            self.assertEqual(plate_api.recognize('synthetic.jpg', min_interval=3), ('', None, 0))
            with self.assertRaises(plate_api.ApiUnavailable):
                plate_api.recognize('synthetic.jpg', min_interval=3)
        self.assertEqual(http.call_count, 1)

    def test_invalid_timeout_and_threshold_use_safe_defaults(self):
        with patch.dict('os.environ', {'PLATE_API_TIMEOUT': 'invalid', 'PLATE_API_MIN_SCORE': 'invalid'}):
            self.assertEqual(plate_api.min_score(), 0.8)
            with patch.object(plate_api, '_encode_image', return_value=(b'jpeg', 1)), \
                    patch.object(plate_api.urllib.request, 'urlopen', return_value=BytesIO(b'{}')) as http:
                plate_api.recognize('synthetic.jpg')
            self.assertEqual(http.call_args.kwargs['timeout'], 5)
