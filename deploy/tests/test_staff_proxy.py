import importlib.util
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location('staff_proxy', Path(__file__).resolve().parents[1] / 'check-staff-proxy.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StaffProxyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.library = Path(self.temp.name)
        (self.library / 'docker').mkdir()
        (self.library / 'docker/libstaff.conf').write_text('server { server_name libstaff.kaztbu.edu.kz; }')
        self.mount = {'type': 'bind', 'source': str(self.library / 'docker/libstaff.conf'),
                      'target': '/etc/nginx/conf.d/libstaff.conf', 'read_only': True}

    def check(self, volumes):
        module.validate({'services': {'app': {'volumes': volumes}}}, self.library)

    def test_project_mount_alone_does_not_enable_staff_virtual_host(self):
        with self.assertRaisesRegex(ValueError, 'read-only mount'):
            self.check([{'type': 'bind', 'source': str(self.library), 'target': '/app'}])

    def test_explicit_staff_mount_is_accepted(self):
        self.check([self.mount])

    def test_wrong_source_or_writable_mount_is_rejected(self):
        for change in ({'source': '/some/other/libstaff.conf'}, {'read_only': False}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.check([{**self.mount, **change}])

    def test_missing_configuration_is_rejected_before_recreation(self):
        (self.library / 'docker/libstaff.conf').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing nginx'):
            self.check([self.mount])

    def test_existing_access_restrictions_must_be_preserved(self):
        (self.library / 'docker/block-catalog-client.conf').write_text('deny 192.0.2.1;')
        with self.assertRaisesRegex(ValueError, 'block-catalog-client.conf'):
            self.check([self.mount])
        self.check([self.mount, {**self.mount,
            'source': str(self.library / 'docker/block-catalog-client.conf'),
            'target': '/etc/nginx/conf.d/block-catalog-client.conf'}])


if __name__ == '__main__':
    unittest.main()
