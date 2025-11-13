#!/usr/bin/env python3
"""
Basic integration tests for DistFS

These tests verify that the core components work together correctly.
Run with: python3 tests/test_basic.py
"""

import json
import os
import sys
import time
import subprocess
import requests

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from distfs_client import DistFSClient


class TestDistFS:
    """Basic integration tests"""

    def __init__(self):
        self.metadata_server = 'localhost:7001'
        self.client = DistFSClient(self.metadata_server)
        self.test_volume_name = 'test-volume-integration'

    def test_metadata_service_health(self):
        """Test metadata service is running and healthy"""
        print("Testing metadata service health...")

        try:
            response = requests.get(f'http://{self.metadata_server}/health', timeout=5)
            assert response.status_code == 200, "Metadata service not healthy"
            data = response.json()
            assert data['status'] == 'healthy', "Metadata service reports unhealthy"
            print("✓ Metadata service is healthy")
            return True
        except Exception as e:
            print(f"✗ Metadata service health check failed: {e}")
            return False

    def test_create_volume(self):
        """Test volume creation"""
        print(f"\nTesting volume creation...")

        try:
            # Clean up if exists
            self.client.delete_volume(self.test_volume_name)

            # Create volume
            volume = self.client.create_volume(
                name=self.test_volume_name,
                size='100M',
                replicas=1
            )

            assert volume['name'] == self.test_volume_name
            assert volume['size_bytes'] == 100 * 1024 * 1024
            assert volume['replicas'] == 1

            print(f"✓ Volume created: {volume['name']} ({volume['size_bytes']} bytes)")
            return True
        except Exception as e:
            print(f"✗ Volume creation failed: {e}")
            return False

    def test_list_volumes(self):
        """Test listing volumes"""
        print("\nTesting volume listing...")

        try:
            volumes = self.client.list_volumes()
            assert isinstance(volumes, list)

            found = any(v['name'] == self.test_volume_name for v in volumes)
            assert found, f"Test volume {self.test_volume_name} not found in list"

            print(f"✓ Found {len(volumes)} volume(s)")
            return True
        except Exception as e:
            print(f"✗ Volume listing failed: {e}")
            return False

    def test_get_volume(self):
        """Test getting volume details"""
        print("\nTesting get volume...")

        try:
            volume = self.client.get_volume(self.test_volume_name)
            assert volume is not None
            assert volume['name'] == self.test_volume_name

            print(f"✓ Retrieved volume: {volume['name']}")
            return True
        except Exception as e:
            print(f"✗ Get volume failed: {e}")
            return False

    def test_list_nodes(self):
        """Test listing storage nodes"""
        print("\nTesting node listing...")

        try:
            nodes = self.client.list_nodes()
            assert isinstance(nodes, list)

            online_nodes = [n for n in nodes if n['status'] == 'online']
            print(f"✓ Found {len(nodes)} node(s), {len(online_nodes)} online")

            if len(online_nodes) == 0:
                print("  ⚠ Warning: No online storage nodes found")

            return True
        except Exception as e:
            print(f"✗ Node listing failed: {e}")
            return False

    def test_health_check(self):
        """Test cluster health check"""
        print("\nTesting cluster health...")

        try:
            health = self.client.health_check()
            assert 'status' in health

            print(f"✓ Cluster status: {health['status']}")
            print(f"  - Nodes: {health.get('online_nodes', 0)}/{health.get('total_nodes', 0)}")
            print(f"  - Volumes: {health.get('total_volumes', 0)}")

            return True
        except Exception as e:
            print(f"✗ Health check failed: {e}")
            return False

    def test_data_operations(self):
        """Test read/write operations"""
        print("\nTesting data operations...")

        # Check if we have storage nodes
        nodes = self.client.list_nodes()
        online_nodes = [n for n in nodes if n['status'] == 'online']

        if len(online_nodes) == 0:
            print("⚠ Skipping data operations test - no online storage nodes")
            return True

        try:
            # Write data
            test_data = b"Hello, DistFS! This is a test." * 100
            success = self.client.write_data(
                self.test_volume_name,
                offset=0,
                data=test_data
            )
            assert success, "Write operation failed"
            print(f"✓ Wrote {len(test_data)} bytes")

            # Read data back
            read_data = self.client.read_data(
                self.test_volume_name,
                offset=0,
                length=len(test_data)
            )
            assert read_data is not None, "Read operation failed"
            assert read_data == test_data, "Read data doesn't match written data"
            print(f"✓ Read {len(read_data)} bytes (data verified)")

            return True
        except Exception as e:
            print(f"✗ Data operations failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def test_delete_volume(self):
        """Test volume deletion"""
        print("\nTesting volume deletion...")

        try:
            success = self.client.delete_volume(self.test_volume_name)
            assert success, "Delete operation failed"

            # Verify it's gone
            volume = self.client.get_volume(self.test_volume_name)
            assert volume is None, "Volume still exists after deletion"

            print(f"✓ Volume deleted: {self.test_volume_name}")
            return True
        except Exception as e:
            print(f"✗ Volume deletion failed: {e}")
            return False

    def run_all_tests(self):
        """Run all tests"""
        print("=" * 70)
        print("DistFS Integration Tests")
        print("=" * 70)

        tests = [
            self.test_metadata_service_health,
            self.test_create_volume,
            self.test_list_volumes,
            self.test_get_volume,
            self.test_list_nodes,
            self.test_health_check,
            self.test_data_operations,
            self.test_delete_volume,
        ]

        results = []
        for test in tests:
            try:
                result = test()
                results.append(result)
            except Exception as e:
                print(f"\n✗ Test {test.__name__} crashed: {e}")
                import traceback
                traceback.print_exc()
                results.append(False)

        print("\n" + "=" * 70)
        print("Test Summary")
        print("=" * 70)

        passed = sum(results)
        total = len(results)

        print(f"Passed: {passed}/{total}")

        if passed == total:
            print("\n✓ All tests passed!")
            return 0
        else:
            print(f"\n✗ {total - passed} test(s) failed")
            return 1


def main():
    """Main test runner"""
    tester = TestDistFS()
    exit_code = tester.run_all_tests()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
