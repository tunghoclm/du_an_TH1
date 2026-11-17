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

    def test_employee_profile_salary_filter_and_export(self):
        self.role('admin')
        resp = self.client.post('/accounts/add', data={
            'username': 'nv_ca_sang',
            'fullname': 'Nguyễn Văn Ca Sáng',
            'password': 'password123',
            'role': 'manager',
            'employee_code': 'NV0099',
            'attendance_code': 'CC99',
            'phone': '0901234567',
            'department': 'Bảo vệ / Trực cổng',
            'position': 'Trưởng ca',
            'salary_type': 'month',
            'salary_amount': '8500000',
            'allowance_enabled': '1',
            'allowance_amount': '500000',
            'deduction_enabled': '1',
            'deduction_amount': '200000',
            'deduction_note': 'Đi muộn / Về sớm',
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('NV0099', resp.text)
        self.assertIn('8.500.000', resp.text)
        self.assertIn('8.800.000', resp.text)

        staff = [s for s in database.get_staff_users() if s['username'] == 'nv_ca_sang'][0]
        self.assertEqual(staff['salary_amount'], 8500000)
        self.assertEqual(staff['allowance_enabled'], 1)

        resp_update = self.client.post(f"/accounts/{staff['id']}/profile", data={
            'fullname': 'Nguyễn Văn Ca Tối',
            'role': 'manager',
            'department': 'Thu ngân',
            'salary_type': 'shift',
            'salary_amount': '350000',
        }, follow_redirects=True)
        self.assertEqual(resp_update.status_code, 200)
        self.assertIn('Nguyễn Văn Ca Tối', resp_update.text)

        resp_filter = self.client.get('/accounts?department=Thu+ng%C3%A2n&q=Ca+T%E1%BB%91i')
        self.assertEqual(resp_filter.status_code, 200)
        self.assertIn('Nguyễn Văn Ca Tối', resp_filter.text)

        resp_export = self.client.get('/accounts/export')
        self.assertEqual(resp_export.status_code, 200)
        self.assertIn('Nguyễn Văn Ca Tối', resp_export.data.decode('utf-8'))

    def test_employee_attendance_check_in_out_and_manual(self):
        self.role('manager')
        r_in = self.client.post('/attendance/check-in', data={'shift_name': 'Ca sáng'}, follow_redirects=True)
        self.assertEqual(r_in.status_code, 200)
        self.assertIsNotNone(database.get_open_attendance(2))

        r_out = self.client.post('/attendance/check-out', follow_redirects=True)
        self.assertEqual(r_out.status_code, 200)
        self.assertIsNone(database.get_open_attendance(2))

        self.role('admin')
        r_manual = self.client.post('/accounts/2/attendance', data={
            'work_date': '2026-11-17',
            'shift_name': 'Ca chiều',
            'zone_name': 'Cổng A',
            'check_in_time': '14:00',
            'check_out_time': '22:00',
            'status': 'completed',
            'note': 'Trực đầy đủ',
        }, follow_redirects=True)
        self.assertEqual(r_manual.status_code, 200)
        self.assertIn('Ca chiều', r_manual.text)
        self.assertIn('8h 00p', r_manual.text)


if __name__ == '__main__':
    unittest.main()

