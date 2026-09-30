"""System metadata follows the API network relationship, using synthetic data."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import serve

class ModuleNetworkIdentityTests(unittest.TestCase):
    def state(self, entries):
        systems = {
            'North system': SimpleNamespace(name='North system', network_id='701',
                sync_id=901, arm=True, cameras={}, get_network_info=AsyncMock()),
            'South system': SimpleNamespace(name='South system', network_id=702,
                sync_id=902, arm=False, cameras={}, get_network_info=AsyncMock()),
        }
        account = SimpleNamespace(sync=systems, homescreen={'sync_modules': entries},
                                  get_homescreen=AsyncMock())
        handler = serve.Handler.__new__(serve.Handler)
        handler.paths = {}
        with patch.object(serve, 'read_entries', return_value=[]), \
             patch.object(serve, 'provenances', return_value={}), \
             patch.object(serve.runtime, 'passages', return_value={}), \
             patch.object(serve.runtime, 'lire_reglages', return_value={'live_auto_stop_seconds': 30}), \
             patch.object(serve.BLINK, 'call', side_effect=lambda read, timeout: asyncio.run(read(account))):
            result = handler.system_state()['systems']
        account.get_homescreen.assert_awaited_once()
        for sync in systems.values():
            sync.get_network_info.assert_awaited_once()
        self.assertEqual([item['armed'] for item in result], [True, False])
        return result

    def test_reordered_modules_with_independent_display_names(self):
        result = self.state([
            {'network_id': '702', 'name': 'Storage south', 'serial': 'SYNTH-S', 'fw_version': '2'},
            {'network_id': 701, 'name': 'Storage north', 'serial': 'SYNTH-N', 'fw_version': '1'},
        ])
        self.assertEqual([item['module_serial'] for item in result], ['SYNTH-N', 'SYNTH-S'])
        self.assertEqual([item['module_firmware'] for item in result], ['1', '2'])

    def test_duplicate_display_names_do_not_merge_networks(self):
        result = self.state([
            {'network_id': 701, 'name': 'Same name', 'serial': 'SYNTH-N'},
            {'network_id': 702, 'name': 'Same name', 'serial': 'SYNTH-S'},
        ])
        self.assertEqual([item['module_serial'] for item in result], ['SYNTH-N', 'SYNTH-S'])

    def test_unmatched_network_has_no_borrowed_metadata(self):
        result = self.state([{'network_id': 701, 'name': 'North system',
                             'serial': 'SYNTH-N', 'fw_version': '1', 'type': 'sm2'}])
        self.assertEqual(result[0]['module_serial'], 'SYNTH-N')
        for field in ('module', 'module_serial', 'module_firmware'):
            self.assertIsNone(result[1][field])

    def test_absent_module_inventory_leaves_metadata_unknown(self):
        result = self.state([])
        self.assertTrue(all(item['module_serial'] is None for item in result))
