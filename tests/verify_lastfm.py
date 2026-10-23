"""Offline provider fixtures: no real accounts or credentials."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock

request = types.ModuleType('requests')
request.RequestException = RuntimeError
sys.modules['requests'] = request
spec = importlib.util.spec_from_file_location('lastfm', Path(__file__).parents[1] / 'utils/lastfm.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class MusicTests(unittest.TestCase):
    def fetch(self, payload):
        response = Mock()
        response.json.return_value = payload
        request.get = Mock(return_value=response)
        result = module.get_now_playing('fixture')
        self.assertEqual(request.get.call_args.kwargs['timeout'], 5)
        self.assertEqual(request.get.call_count, 1)
        return result

    def test_current_and_last_played(self):
        track = {'artist': {'#text': 'Artist'}, 'name': 'Song', 'url': 'https://www.last.fm/music/test',
            'image': [{'#text': ''}, {'#text': 'https://example.invalid/art.png'}], '@attr': {'nowplaying': 'true'}}
        result = self.fetch({'recenttracks': {'track': [track]}})
        self.assertTrue(result['is_now_playing'])
        self.assertEqual(result['track'], 'Artist – Song')
        self.assertEqual(result['album_art'], 'https://example.invalid/art.png')
        del track['@attr']
        result = self.fetch({'recenttracks': {'track': [track]}})
        self.assertFalse(result['is_now_playing'])
        self.assertEqual(result['track'], 'Artist – Song')

    def test_missing_and_malformed(self):
        for payload in [{}, {'error': 6}, {'recenttracks': {'track': []}},
                {'recenttracks': {'track': [{}]}}, {'recenttracks': {'track': None}}, None]:
            with self.subTest(payload=payload):
                self.assertIsNone(self.fetch(payload)['track'])

    def test_provider_failure(self):
        request.get = Mock(side_effect=RuntimeError('offline'))
        self.assertIsNone(module.get_now_playing('fixture')['track'])

    def test_missing_art(self):
        self.assertIsNone(self.fetch({'recenttracks': {'track': [{'name': 'Song'}]}})['album_art'])

if __name__ == '__main__':
    unittest.main()
