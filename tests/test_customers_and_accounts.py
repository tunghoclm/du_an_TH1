"""Kiểm tra chức năng tách riêng Quản lý Khách hàng và Quản lý Tài khoản nhân viên/hệ thống.
"""
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py'))

import test_gate
import database


class CustomerAndAccountTests(unittest.TestCase):
    setUpClass = classmethod(test_gate.GateTests.setUpClass.__func__)
    tearDownClass = classmethod(test_gate.GateTests.tearDownClass.__func__)
    setUp = test_gate.GateTests.setUp

    def role(self, role):
        with self.client.session_transaction() as session:
            session['role'] = role
            session['user_id'] = 1 if role == 'admin' else 2
            session['username'] = role + '-test'

    def test_customers_page_accessible_by_staff_and_admin(self):
        for role in ('admin', 'manager'):
            self.role(role)
            resp = self.client.get('/customers')
            self.assertEqual(resp.status_code, 200)
            self.assertIn('Quản lý Khách hàng', resp.text)

    def test_accounts_page_only_accessible_by_admin(self):
        self.role('manager')
        resp = self.client.get('/accounts')
        self.assertEqual(resp.status_code, 302)  # manager redirected

        self.role('admin')
        resp = self.client.get('/accounts')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Tài khoản Nhân viên', resp.text)

    def test_create_customer_appears_only_in_customer_list(self):
        self.role('admin')
        resp = self.client.post('/customers/add', data={
            'username': 'khachhang01',
            'fullname': 'Khách Hàng Một',
            'password': 'password123'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        cust = database.get_customer_users()
        self.assertTrue(any(c['username'] == 'khachhang01' for c in cust))

        staff = database.get_staff_users()
        self.assertFalse(any(s['username'] == 'khachhang01' for s in staff))

    def test_create_staff_account_appears_only_in_account_list(self):
        self.role('admin')
        resp = self.client.post('/accounts/add', data={
            'username': 'nhanvien_moi',
            'fullname': 'Nhân Viên Mới',
            'password': 'password123',
            'role': 'manager'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        staff = database.get_staff_users()
        self.assertTrue(any(s['username'] == 'nhanvien_moi' for s in staff))

        cust = database.get_customer_users()
        self.assertFalse(any(c['username'] == 'nhanvien_moi' for c in cust))

    def test_users_route_redirects_appropriately(self):
        self.role('admin')
        resp = self.client.get('/users')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/customers', resp.headers['Location'])

        resp = self.client.get('/users?tab=accounts')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts', resp.headers['Location'])

    def test_cannot_lock_or_delete_primary_admin(self):
        self.role('admin')
        resp = self.client.post('/users/1/toggle', follow_redirects=True)
        admin = database.get_user_by_id(1)
        self.assertEqual(admin['status'], 'active')

        resp = self.client.post('/users/1/delete', follow_redirects=True)
        admin = database.get_user_by_id(1)
        self.assertIsNotNone(admin)


if __name__ == '__main__':
    unittest.main()

