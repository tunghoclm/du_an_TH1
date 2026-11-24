"""Kiểm tra chức năng tách riêng Quản lý Khách hàng và Quản lý Tài khoản nhân viên/hệ thống.
"""
import sys
from pathlib import Path
import unittest

import openpyxl
import reportlab.platypus

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py'))
sys.path.insert(0, str(ROOT / 'tests'))

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
            'salary_type': 'shift',
            'salary_amount': '350000',
        }, follow_redirects=True)
        self.assertEqual(resp_update.status_code, 200)
        self.assertIn('Nguyễn Văn Ca Tối', resp_update.text)

        resp_filter = self.client.get('/accounts?q=Ca+T%E1%BB%91i')
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

    def test_employee_payroll_display_calculation_and_export(self):
        from io import BytesIO

        self.role('admin')
        # Tạo nhân viên lương theo ca (300.000 đ/ca) + phụ cấp 200.000 đ
        r_add = self.client.post('/accounts/add', data={
            'username': 'nv_luong_ca',
            'fullname': 'Trần Thị Lương Ca',
            'password': 'password123',
            'role': 'manager',
            'employee_code': 'NV0888',
            'salary_type': 'shift',
            'salary_amount': '300000',
            'allowance_enabled': '1',
            'allowance_amount': '200000',
        }, follow_redirects=True)
        self.assertEqual(r_add.status_code, 200)
        emp = [s for s in database.get_staff_users() if s['username'] == 'nv_luong_ca'][0]

        # Chấm công 2 ca trong tháng 2026-11 -> 2 * 300.000 + 200.000 = 800.000 đ
        for day in ('2026-11-10', '2026-11-11'):
            self.client.post(f"/accounts/{emp['id']}/attendance", data={
                'work_date': day,
                'shift_name': 'Ca sáng',
                'check_in_time': '07:00',
                'check_out_time': '15:00',
                'status': 'completed',
            })

        r_page = self.client.get('/accounts?month=2026-11')
        self.assertEqual(r_page.status_code, 200)
        self.assertIn('300.000 đ/ca', r_page.text)
        self.assertIn('800.000 đ', r_page.text)
        self.assertIn('Tổng quỹ lương thực nhận', r_page.text)

        # Xuất bảng lương Excel (.xlsx)
        r_xlsx = self.client.get(f"/accounts/payroll/export?format=xlsx&month=2026-11&ids={emp['id']}")
        self.assertEqual(r_xlsx.status_code, 200)
        self.assertIn('spreadsheetml', r_xlsx.content_type)
        wb = openpyxl.load_workbook(BytesIO(r_xlsx.data))
        ws = wb.active
        self.assertEqual(ws['A1'].value, 'BẢNG LƯƠNG NHÂN VIÊN')
        self.assertEqual(ws.cell(row=5, column=4).value, 'Trần Thị Lương Ca')
        self.assertEqual(ws.cell(row=5, column=9).value, 600000)
        self.assertEqual(ws.cell(row=5, column=13).value, 800000)

        # Xuất bảng lương PDF (.pdf)
        r_pdf = self.client.get(f"/accounts/payroll/export?format=pdf&month=2026-11&ids={emp['id']}")
        self.assertEqual(r_pdf.status_code, 200)
        self.assertEqual(r_pdf.content_type, 'application/pdf')
        self.assertTrue(r_pdf.data.startswith(b'%PDF-'))

        # Xuất bảng lương CSV (.csv)
        r_csv = self.client.get(f"/accounts/payroll/export?format=csv&month=2026-11&ids={emp['id']}")
        self.assertEqual(r_csv.status_code, 200)
        csv_text = r_csv.data.decode('utf-8')
        self.assertIn('Trần Thị Lương Ca', csv_text)
        self.assertIn('800000', csv_text)
        self.assertIn('TỔNG CỘNG', csv_text)

        # Xuất danh sách nhân viên Excel (.xlsx) và PDF (.pdf)
        r_emp_xlsx = self.client.get(f"/accounts/export?format=xlsx&ids={emp['id']}")
        self.assertEqual(r_emp_xlsx.status_code, 200)
        self.assertIn('spreadsheetml', r_emp_xlsx.content_type)
        wb_emp = openpyxl.load_workbook(BytesIO(r_emp_xlsx.data))
        self.assertEqual(wb_emp.active['A1'].value, 'DANH SÁCH NHÂN VIÊN')
        self.assertEqual(wb_emp.active.cell(row=5, column=3).value, 'Trần Thị Lương Ca')

        r_emp_pdf = self.client.get(f"/accounts/export?format=pdf&ids={emp['id']}")
        self.assertEqual(r_emp_pdf.status_code, 200)
        self.assertEqual(r_emp_pdf.content_type, 'application/pdf')
        self.assertTrue(r_emp_pdf.data.startswith(b'%PDF-'))

    def test_employee_suite_pages_and_actions(self):
        from datetime import date
        self.role('admin')
        # 1. Topbar dropdown links render on /accounts
        r_acc = self.client.get('/accounts')
        self.assertEqual(r_acc.status_code, 200)
        self.assertIn('/employees/schedule', r_acc.text)
        self.assertIn('/employees/timesheet', r_acc.text)
        self.assertIn('/employees/payroll', r_acc.text)

        # 2. Lịch làm việc: GET + POST add + delete
        r_sch = self.client.get('/employees/schedule')
        self.assertEqual(r_sch.status_code, 200)
        self.assertIn('Lịch làm việc', r_sch.text)
        r_sch_add = self.client.post('/employees/schedule', data={
            'user_id': '2',
            'work_date': date.today().isoformat(),
            'shift_name': 'Ca sáng',
            'gate_name': 'Cổng chính',
            'note': 'Trực đầu ca',
        }, follow_redirects=True)
        self.assertEqual(r_sch_add.status_code, 200)
        self.assertIn('Ca sáng', r_sch_add.text)

        # 3. Bảng chấm công: GET + POST
        r_ts = self.client.get('/employees/timesheet')
        self.assertEqual(r_ts.status_code, 200)
        self.assertIn('Bảng chấm công', r_ts.text)
        r_ts_add = self.client.post('/employees/timesheet', data={
            'user_id': '2',
            'work_date': date.today().isoformat(),
            'shift_name': 'Ca chiều',
            'zone_name': 'Cổng chính',
            'check_in_time': '14:00',
            'check_out_time': '22:00',
            'status': 'completed',
        }, follow_redirects=True)
        self.assertEqual(r_ts_add.status_code, 200)
        self.assertIn('Ca chiều', r_ts_add.text)

        # 4. Bảng lương: GET + POST create + status update
        r_pr = self.client.get('/employees/payroll')
        self.assertEqual(r_pr.status_code, 200)
        self.assertIn('Bảng tính lương', r_pr.text)
        r_pr_add = self.client.post('/employees/payroll', data={
            'name': 'Bảng lương test T11',
            'pay_cycle': 'Hàng tháng',
            'work_period': date.today().strftime('%Y-%m'),
            'pay_branch': 'Cổng chính',
        }, follow_redirects=True)
        self.assertEqual(r_pr_add.status_code, 200)
        self.assertIn('Bảng lương test T11', r_pr_add.text)

        # 5. Thiết lập nhân viên nằm trong phân hệ Nhân viên (/employees/settings)
        r_set = self.client.get('/employees/settings')
        self.assertEqual(r_set.status_code, 200)
        self.assertIn('Thiết lập nhanh', r_set.text)
        r_wd = self.client.post('/employees/settings', data={
            'emp_action': 'save_work_days',
            'gate_name': 'Cổng chính',
            'work_days': ['T2', 'T3', 'T4', 'T5', 'T6'],
        }, follow_redirects=True)
        self.assertEqual(r_wd.status_code, 200)
        self.assertIn('T2, T3, T4, T5, T6', r_wd.text)
        r_hol = self.client.post('/employees/settings', data={
            'emp_action': 'add_holiday',
            'holiday_name': 'Tết Dương lịch',
            'start_date': '2026-01-01',
            'end_date': '2026-01-01',
            'holiday_bonus': '500000',
        }, follow_redirects=True)
        self.assertEqual(r_hol.status_code, 200)
        self.assertIn('Tết Dương lịch', r_hol.text)
        r_qadd = self.client.post('/employees/settings', data={
            'emp_action': 'quick_add_employees',
            'emp_fullname': ['Lê Văn Nhanh'],
            'emp_phone': ['0911222333'],
            'emp_pay_branch': ['Cổng chính'],
            'emp_work_branch': ['Cổng chính'],
        }, follow_redirects=True)
        self.assertEqual(r_qadd.status_code, 200)
        self.assertIn('Đã thêm nhanh 1 nhân viên', r_qadd.text)
        r_qsal = self.client.post('/employees/settings', data={
            'emp_action': 'quick_save_salary',
            'user_id': '2',
            'salary_type': 'hour',
            'salary_amount': '25000',
            'allowance_enabled': '1',
            'allowance_amount': '200000',
        }, follow_redirects=True)
        self.assertEqual(r_qsal.status_code, 200)
        self.assertIn('Đã cập nhật thiết lập lương', r_qsal.text)
        r_attm = self.client.post('/employees/settings', data={
            'emp_action': 'quick_save_attendance_mode',
            'emp_attendance_mode': 'flex',
        }, follow_redirects=True)
        self.assertEqual(r_attm.status_code, 200)
        self.assertIn('Chấm công theo khung giờ làm việc', r_attm.text)
        r_cim = self.client.post('/employees/settings', data={
            'emp_action': 'quick_save_checkin_methods',
            'emp_checkin_software': '1',
            'emp_checkin_photo': '1',
        }, follow_redirects=True)
        self.assertEqual(r_cim.status_code, 200)
        self.assertIn('Qua phần mềm, Chụp ảnh', r_cim.text)
        r_sh = self.client.post('/employees/settings', data={
            'emp_action': 'save_shift',
            'shift_name': 'Ca tăng cường',
            'shift_start': '08:00',
            'shift_end': '12:00',
            'checkin_start': '07:30',
            'checkin_end': '12:30',
            'shift_gates': ['Cổng chính'],
        }, follow_redirects=True)
        self.assertEqual(r_sh.status_code, 200)
        self.assertIn('Ca tăng cường', r_sh.text)
        r_tpl = self.client.post('/employees/settings', data={
            'emp_action': 'save_salary_template',
            'tpl_name': 'Mẫu trực đêm',
            'tpl_salary_type': 'shift',
            'tpl_salary_amount': '350000',
            'tpl_allowance_enabled': '1',
            'tpl_allowance_amount': '100000',
        }, follow_redirects=True)
        self.assertEqual(r_tpl.status_code, 200)
        self.assertIn('Mẫu trực đêm', r_tpl.text)
        r_apply = self.client.post('/employees/settings', data={
            'emp_action': 'apply_salary_template',
            'tpl_name': 'Mẫu trực đêm',
            'user_ids': ['2'],
        }, follow_redirects=True)
        self.assertEqual(r_apply.status_code, 200)
        self.assertIn('1 nhân viên', r_apply.text)
        r_alw = self.client.post('/employees/settings', data={
            'emp_action': 'save_allowance',
            'item_name': 'Phụ cấp xăng xe',
            'item_type': 'Phụ cấp cố định hàng tháng',
            'item_amount': '300000',
        }, follow_redirects=True)
        self.assertEqual(r_alw.status_code, 200)
        self.assertIn('Phụ cấp xăng xe', r_alw.text)
        r_ded = self.client.post('/employees/settings', data={
            'emp_action': 'save_deduction',
            'item_name': 'Quên bấm thẻ',
            'item_type': 'Vi phạm nội quy',
            'item_amount': '100000',
        }, follow_redirects=True)
        self.assertEqual(r_ded.status_code, 200)
        self.assertIn('Quên bấm thẻ', r_ded.text)
        r_acc2 = self.client.get('/accounts')
        self.assertIn('Mẫu trực đêm', r_acc2.text)
        self.assertIn('Quên bấm thẻ', r_acc2.text)
        r_gen_set = self.client.get('/settings')
        self.assertEqual(r_gen_set.status_code, 200)
        self.assertNotIn('/settings?section=employee', r_gen_set.text)

    def test_customer_vehicles_always_require_monthly_ticket(self):
        self.role('admin')
        page = self.client.get('/customers')
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('data-edit-ticket-select', page.text)
        self.assertNotIn('data-ticket-select', page.text)
        self.assertIn('data-payment-box', page.text)
        self.assertIn('data-vietqr', page.text)

        month_period = next((p for p in database.get_periods() if p['kind'] == 'day'), None)
        self.assertIsNotNone(month_period)
        database.save_price(None, self.type_id, month_period['id'], 120000, 'month')

        resp = self.client.post('/customers/add', data={
            'username': 'khach_ve_thang',
            'fullname': 'Khách Vé Tháng',
            'password': 'password123',
            'plate': '59A1-99887',
            'vehicle_type_id': str(self.type_id),
            'ticket_type': 'turn',  # Ngay cả khi gửi 'turn', backend vẫn ép thành 'month'
            'months': '2',
            'payment_method': 'transfer',
        })
        self.assertEqual(resp.status_code, 302)
        user = next(u for u in database.get_customer_users() if u['username'] == 'khach_ve_thang')
        vehicles = database.get_user_vehicles(user['id'])
        self.assertEqual(len(vehicles), 1)
        self.assertEqual(vehicles[0]['ticket_type'], 'month')
        self.assertEqual(vehicles[0]['months'], 2)
        self.assertEqual(vehicles[0]['paid_amount'], 240000)
        self.assertIsNotNone(vehicles[0]['expires_on'])

        conn = database.get_connection()
        payment = conn.execute(
            "SELECT amount, months, payment_method FROM ticket_payments WHERE user_vehicle_id=?",
            (vehicles[0]['id'],),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(payment)
        self.assertEqual((payment['amount'], payment['months'], payment['payment_method']), (240000, 2, 'transfer'))

        # Gia hạn thêm 1 tháng bằng thẻ
        renew_resp = self.client.post(f"/users/{user['id']}/vehicles/{vehicles[0]['id']}/renew", data={
            'months': '1',
            'payment_method': 'card',
            'next': 'customers',
        })
        self.assertEqual(renew_resp.status_code, 302)
        conn = database.get_connection()
        payments = conn.execute(
            "SELECT amount, months, payment_method FROM ticket_payments WHERE user_vehicle_id=? ORDER BY id",
            (vehicles[0]['id'],),
        ).fetchall()
        conn.close()
        self.assertEqual(len(payments), 2)
        self.assertEqual((payments[1]['amount'], payments[1]['months'], payments[1]['payment_method']), (120000, 1, 'card'))

    def test_employee_kiotviet_permissions_modal_and_save(self):
        import json
        self.role('admin')
        self.client.post('/accounts/add', data={
            'username': 'nv_phanquyen',
            'fullname': 'Nhân Viên Phân Quyền',
            'password': 'password123',
            'role': 'manager',
        })
        emp = next(s for s in database.get_staff_users() if s['username'] == 'nv_phanquyen')

        page = self.client.get('/accounts')
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="edit-permissions-dialog"', page.text)
        self.assertIn('Phân quyền theo vai trò', page.text)
        self.assertIn('Phân quyền khác', page.text)

        payload = {
            'gates': {
                'Cổng chính': {
                    'role_preset': 'Nhân viên vận hành',
                    'perms': ['dashboard.view', 'gate.view', 'invoices.view', 'invoices.print', 'staff.view'],
                },
            },
            'other': {
                'view_shared_info': True,
                'manage_other_staff_eod': False,
            },
        }
        resp = self.client.post(f"/accounts/{emp['id']}/permissions", data={
            'permissions_json': json.dumps(payload),
        })
        self.assertEqual(resp.status_code, 302)
        updated = database.get_user_by_id(emp['id'])
        saved = json.loads(updated['permissions_json'])
        self.assertEqual(saved['gates']['Cổng chính']['role_preset'], 'Nhân viên vận hành')
        self.assertTrue(saved['other']['view_shared_info'])
        self.assertFalse(saved['other']['manage_other_staff_eod'])

        # Kiểm tra quyền được thực thi thực tế khi nhân viên đăng nhập:
        # Cấp staff.view, không cấp reports.view / customers.create / parking.create / pricing.edit
        with self.client.session_transaction() as sess:
            sess['user_id'] = emp['id']
            sess['username'] = emp['username']
            sess['role'] = 'manager'
        self.assertEqual(self.client.get('/accounts').status_code, 200)
        self.assertEqual(self.client.get('/statistics').status_code, 302)
        self.assertEqual(self.client.post('/customers/add', data={'username': 'x', 'fullname': 'X', 'password': 'password123'}).status_code, 302)
        self.assertEqual(self.client.post('/parking/areas/save', data={'name': 'Z', 'slot_count': '2'}).status_code, 302)
        self.assertEqual(self.client.post('/pricing/period/save', data={'name': 'Ca'}).status_code, 302)
        self.assertFalse(database.username_exists('x'))


if __name__ == '__main__':
    unittest.main()

